# 业务层：把库里的聊天记录收成给模型看的文本。权限在这里判断。

from ..data.store import HistoryStore
from ..entity.record import ChatRecord
from .auth import group_id_of, guard, is_astrbot_admin
from .parse import format_ts, hours_ago_ts
from .settings import get_bool, get_int


async def read_history(
    store: HistoryStore,
    event: object,
    config: object,
    hours: float,
    max_messages: int,
) -> str:
    """取出本群最近一段时间的聊天记录，供模型总结。"""
    group_id = group_id_of(event)
    # 私聊没有群号，读不了本群记录
    if not group_id:
        return "该操作只能在群聊中使用。"
    # 聊天记录涉及他人隐私，默认只给操作者看
    if get_bool(config, "history_operator_only", True):
        err = await _history_permission(event, config, group_id)
        # 没过权限不把别人聊天记录交出去
        if err:
            return err
    # 配置关掉记录时，库里也读不出有意义的内容
    if not get_bool(config, "enable_history", True):
        return "聊天记录功能已被插件配置禁用（enable_history=false）。"
    limit_cfg = get_int(config, "summary_max_messages", 300)
    limit = max_messages if max_messages > 0 else limit_cfg
    # 模型要的条数不能超过配置上限，防止一次吃光 token
    limit = min(limit, limit_cfg)
    hours_val = hours
    # 模型传 0 或负数时按 24 小时算
    if hours_val <= 0:
        hours_val = 24
    since_ts = hours_ago_ts(hours_val)
    try:
        records = await store.fetch(str(group_id), since_ts, limit)
    except Exception as exc:
        return f"读取聊天记录失败：{exc}"
    # 空结果要说清是真没记过，不是工具坏了
    if not records:
        return f"最近 {hours_val:g} 小时内没有记录。只有机器人运行期间收到的群消息才会入库。"
    return _format_records(records, hours_val)


async def _history_permission(event: object, config: object, group_id: object) -> str:
    """聊天记录的权限。AstrBot 管理员直接过；其他人走和群管一样的检查。"""
    # 后台管理员可以跨群查记录
    if is_astrbot_admin(event):
        return ""
    _gid, err = await guard(event, config)
    return err


def _format_records(records: list[ChatRecord], hours: float) -> str:
    """把记录收成时间正序的纯文本。"""
    lines = []
    for rec in records:
        lines.append(f"[{format_ts(rec.ts)}] {rec.name}({rec.uid}): {rec.text}")
    header = f"最近 {hours:g} 小时共 {len(records)} 条：\n"
    return header + "\n".join(lines)
