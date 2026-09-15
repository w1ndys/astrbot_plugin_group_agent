# 业务层：撤回本群消息。协议端只认内存里还记得的短 ID。

from ..entity.constants import RECALL_RECENT_MAX
from .auth import guard
from .history import live_recent_ids
from .onebot import call_action
from .parse import parse_int
from .settings import get_bool


async def recall_one(event: object, config: object, message_id: str) -> str:
    """撤回一条指定消息。"""
    err = _recall_enabled(config)
    # 配置关掉撤回时直接拒绝
    if err:
        return err
    _group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    mid = parse_int(message_id)
    # 协议端要的是数字短 ID，字符串或空值都撤不了
    if mid is None:
        return f"message_id 不合法：{message_id!r}。需要数字消息 ID。"
    ok, _data, api_err = await call_action(event, config, "delete_msg", message_id=mid)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已撤回消息 {mid}。"


async def recall_recent(event: object, config: object, store: object, count: int) -> str:
    """撤回本群最近若干条已入库、且带消息 ID 的记录。"""
    err = _recall_enabled(config)
    # 配置关掉撤回时直接拒绝
    if err:
        return err
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    n = _clip_count(count)
    ids = await store.recent_ids(str(group_id), n)
    # 库里没有消息 ID 时改问协议端，那个短 ID 才能拿去撤回
    if not ids:
        ids = await live_recent_ids(event, config, group_id, n)
    # 本地和协议端都没有可撤回的 ID
    if not ids:
        return "最近没有可撤回的消息。"
    ok_n = 0
    fail_n = 0
    last_err = ""
    for mid in ids:
        parsed = parse_int(mid)
        # 库里偶发脏 ID，跳过不算成功
        if parsed is None:
            fail_n += 1
            continue
        ok, _data, api_err = await call_action(event, config, "delete_msg", message_id=parsed)
        # 协议端成功才计数
        if ok:
            ok_n += 1
        # 失败记条数，并留下最后一次原因给全失败时回填
        else:
            fail_n += 1
            last_err = api_err
    # 一条都没撤成时，把最后一次原因回给模型
    if ok_n == 0:
        return last_err or "撤回失败。"
    # 部分成功时把失败条数说清楚，方便模型决定要不要再试
    if fail_n:
        return f"已撤回 {ok_n} 条，{fail_n} 条失败。"
    return f"已撤回最近 {ok_n} 条。"


def _recall_enabled(config: object) -> str:
    """撤回总开关。关了就不要发协议请求。"""
    # 配置关掉撤回时直接拒绝，避免误撤
    if not get_bool(config, "allow_recall", True):
        return "撤回功能已被插件配置禁用。"
    return ""


def _clip_count(count: object) -> int:
    """把模型要的条数夹到 1..上限。"""
    parsed = parse_int(count)
    # 没给或给的不合法时默认 1 条
    if parsed is None or parsed < 1:
        return 1
    # 超过上限夹住，避免一次把最近十几条全撤掉
    if parsed > RECALL_RECENT_MAX:
        return RECALL_RECENT_MAX
    return parsed
