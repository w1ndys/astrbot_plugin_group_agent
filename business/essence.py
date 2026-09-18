# 业务层：群精华消息。列表给后续工具用，不要念给用户。

from ..entity.constants import ESSENCE_SHOW_LIMIT
from .auth import guard_group, guard_group_write
from .onebot import call_action, unwrap_list
from .parse import clip_text, parse_int


async def list_essence(event: object, config: object, group_id: str = "") -> str:
    """拉精华列表。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(
        event, config, "get_essence_msg_list", group_id=str(target)
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = [x for x in unwrap_list(result) if isinstance(x, dict)]
    # 没有精华
    if not items:
        return "这个群没有精华消息。"
    shown = items[:ESSENCE_SHOW_LIMIT]
    lines = [_format_essence(item) for item in shown]
    head = f"精华 {len(items)} 条。以下仅供后续工具使用，不要念给用户"
    # 太多只给前 N
    if len(items) > ESSENCE_SHOW_LIMIT:
        head += f"；只返回前 {ESSENCE_SHOW_LIMIT} 条"
    return head + "。\n" + "\n".join(lines)


def _format_essence(item: dict) -> str:
    """一条精华：消息 ID、发送人、摘要。"""
    mid = item.get("message_id") or ""
    sender = item.get("sender_nick") or item.get("sender_id") or ""
    text = clip_text(_content_text(item.get("content")), 80)
    return f"#{mid}  {sender}  {text}"


def _content_text(content: object) -> str:
    """精华 content 可能是段列表。"""
    # 纯文本
    if isinstance(content, str):
        return content
    # 不是列表就原样
    if not isinstance(content, list):
        return str(content or "")
    parts = []
    for seg in content:
        # 脏数据跳过
        if not isinstance(seg, dict):
            continue
        data = seg.get("data")
        # data 里才有 text
        if isinstance(data, dict) and data.get("text"):
            parts.append(str(data.get("text")))
    return "".join(parts)


async def set_essence(event: object, config: object, message_id: str, group_id: str = "") -> str:
    """把一条消息设为精华。"""
    _target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    mid = parse_int(str(message_id or "").lstrip("#"))
    # 必须是数字消息 ID
    if mid is None:
        return "message_id 必须是数字。"
    ok, _data, api_err = await call_action(event, config, "set_essence_msg", message_id=mid)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已设为精华：{mid}。"


async def delete_essence(
    event: object, config: object, message_id: str, group_id: str = ""
) -> str:
    """移出精华。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    mid = parse_int(str(message_id or "").lstrip("#"))
    # 必须是数字消息 ID
    if mid is None:
        return "message_id 必须是数字。"
    ok, _data, api_err = await call_action(
        event, config, "delete_essence_msg", message_id=mid, group_id=str(target)
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已移出精华：{mid}。"
