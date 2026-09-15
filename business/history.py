# 业务层：把库里的聊天记录收成给模型看的文本。权限在这里判断。
# 库里没有消息 ID 时，改走协议端 get_group_msg_history，那个 ID 才能用来撤回。

from ..data.store import HistoryStore
from ..entity.constants import HISTORY_API_DEFAULT, HISTORY_API_MAX
from ..entity.record import ChatRecord
from .auth import group_id_of, guard, is_astrbot_admin
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import clip_text, format_ts, hours_ago_ts, parse_int
from .settings import get_bool, get_int


async def read_history(
    store: HistoryStore,
    event: object,
    config: object,
    hours: float,
    max_messages: int,
) -> str:
    """取出本群最近聊天记录。本地有消息 ID 就用库，没有就问协议端。"""
    group_id = group_id_of(event)
    # 私聊没有群号，读不了本群记录
    if not group_id:
        return "该操作只能在群聊中使用。"
    err = await _history_permission_if_needed(event, config, group_id)
    # 没过权限不把别人聊天记录交出去
    if err:
        return err
    limit = _history_limit(config, max_messages)
    hours_val = hours if hours > 0 else 24
    live = await read_live_history(event, config, group_id, limit)
    # 协议端短 ID 才能拿去撤回，有结果就优先用它
    if live:
        return live
    records = await _load_local(store, config, str(group_id), hours_val, limit)
    # 协议端没给时，退回本地库，至少还能总结
    if records:
        return _format_records(records, hours_val)
    return f"最近 {hours_val:g} 小时内没有记录。只有机器人运行期间收到的群消息才会入库。"


async def _history_permission_if_needed(event: object, config: object, group_id: object) -> str:
    """聊天记录涉及他人隐私，默认只给操作者看。"""
    # 配置关掉仅操作者可见时，谁都能读
    if not get_bool(config, "history_operator_only", True):
        return ""
    return await _history_permission(event, config, group_id)


async def _history_permission(event: object, config: object, group_id: object) -> str:
    """聊天记录的权限。AstrBot 管理员直接过；其他人走和群管一样的检查。"""
    # 后台管理员可以跨群查记录
    if is_astrbot_admin(event):
        return ""
    _gid, err = await guard(event, config)
    return err


def _history_limit(config: object, max_messages: int) -> int:
    """把模型要的条数夹到配置上限以内。"""
    limit_cfg = get_int(config, "summary_max_messages", 300)
    limit = max_messages if max_messages > 0 else limit_cfg
    # 模型要的条数不能超过配置上限，防止一次吃光 token
    return min(limit, limit_cfg)


async def _load_local(
    store: HistoryStore,
    config: object,
    group_id: str,
    hours_val: float,
    limit: int,
) -> list[ChatRecord]:
    """读本地库。记录功能关掉时不当作失败，后面还会问协议端。"""
    # 配置关掉记录时，库里没有新数据，别去查
    if not get_bool(config, "enable_history", True):
        return []
    try:
        return await store.fetch(group_id, hours_ago_ts(hours_val), limit)
    except Exception:
        return []


def _format_records(records: list[ChatRecord], hours: float) -> str:
    """把记录收成时间正序的纯文本。每条带消息 ID，撤回时要用。"""
    lines = []
    for rec in records:
        mark = f" #{rec.message_id}" if rec.message_id else ""
        lines.append(f"[{format_ts(rec.ts)}]{mark} {rec.name}({rec.uid}): {rec.text}")
    header = f"最近 {hours:g} 小时共 {len(records)} 条：\n"
    return header + "\n".join(lines)


async def read_live_history(event: object, config: object, group_id: object, limit: int) -> str:
    """从协议端拉最近消息。失败返回空，让调用方回退到本地库。"""
    items = await _live_messages(event, config, group_id, limit)
    # 协议端没给列表就当失败
    if not items:
        return ""
    return _format_live_list(items)


async def live_recent_ids(event: object, config: object, group_id: object, count: int) -> list[str]:
    """从协议端取最近若干条消息 ID，按新到旧。给撤回最近 N 条用。"""
    items = await _live_messages(event, config, group_id, count)
    ids = []
    for item in reversed(items):
        mid = _item_id(item)
        # 没有 ID 的脏数据跳过
        if not mid:
            continue
        ids.append(mid)
        # 够了就停
        if len(ids) >= count:
            break
    return ids


async def _live_messages(
    event: object, config: object, group_id: object, limit: int
) -> list[object]:
    """调 get_group_msg_history，统一抽成消息列表。"""
    count = _clip_api_count(limit)
    ok, result, _err = await call_action(
        event,
        config,
        "get_group_msg_history",
        group_id=str(group_id),
        count=count,
    )
    # 协议失败时返回空列表，由调用方决定怎么说
    if not ok:
        return []
    return _unwrap_messages(result)


def _clip_api_count(limit: int) -> int:
    """协议端拉历史的条数夹到默认和上限之间。"""
    # 没给或给太小就用默认 20
    if limit <= 0:
        return HISTORY_API_DEFAULT
    # 太大协议端会慢，夹到上限
    if limit > HISTORY_API_MAX:
        return HISTORY_API_MAX
    return limit


def _unwrap_messages(result: object) -> list[object]:
    """协议端有的直接给列表，有的包在 messages 里。"""
    # 直接就是列表
    if isinstance(result, list):
        return result
    data = unwrap_dict(result)
    msgs = data.get("messages")
    # 标准结构 {messages: [...]}
    if isinstance(msgs, list):
        return msgs
    return unwrap_list(result)


def _format_live_list(items: list[object]) -> str:
    """把协议端消息收成和本地库同一套格式，方便模型接着撤回。"""
    lines = []
    for item in items:
        line = _format_live_one(item)
        # 脏数据跳过
        if line:
            lines.append(line)
    # 过滤后什么都没剩
    if not lines:
        return ""
    return f"本群最近 {len(lines)} 条（来自协议端，可撤回）：\n" + "\n".join(lines)


def _format_live_one(item: object) -> str:
    """一条协议端消息。群名片和昵称都写上，避免只对上其中一个。"""
    # 非 dict 没法取字段
    if not isinstance(item, dict):
        return ""
    mid = _item_id(item)
    uid = item.get("user_id") or ""
    name = _sender_name(item.get("sender"))
    ts = parse_int(item.get("time")) or 0
    text = clip_text(str(item.get("raw_message") or "").strip(), 300)
    mark = f" #{mid}" if mid else ""
    when = format_ts(ts) if ts else "时间未知"
    return f"[{when}]{mark} {name}({uid}): {text}"


def _item_id(item: object) -> str:
    """从一条协议端消息里取出短 ID。"""
    # 非 dict 没有 message_id
    if not isinstance(item, dict):
        return ""
    raw = item.get("message_id")
    # 缺字段或空值都当没有
    if raw is None or raw == "":
        return ""
    return str(raw)


def _sender_name(sender: object) -> str:
    """群名片优先，和昵称不同时两个都写，方便对上「Giant_GKL / MiniMax H3」。"""
    # sender 不是 dict 时只能写未知
    if not isinstance(sender, dict):
        return "未知用户"
    card = str(sender.get("card") or "").strip()
    nick = str(sender.get("nickname") or "").strip()
    # 名片和昵称都有且不同，两个都给模型看
    if card and nick and card != nick:
        return f"{card}/{nick}"
    return card or nick or "未知用户"
