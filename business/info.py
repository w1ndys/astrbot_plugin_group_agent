# 业务层：群信息、群公告、禁言列表。
# 读取走 guard_readonly（不要求机器人是管理员），发布公告走 guard（需要管理员）。

import html

from ..entity.constants import (
    NOTICE_MAX_LIMIT,
    NOTICE_SHOW_LIMIT,
    NOTICE_TEXT_LIMIT,
)
from .auth import guard, guard_group_write, guard_readonly
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import clip_text, format_ts, parse_int
from .settings import get_bool


async def query_group_info(event: object, config: object) -> str:
    """查本群基本信息：群名、人数、上限、全员禁言、群主。"""
    group_id, err = await guard_readonly(event, config)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "get_group_info", group_id=group_id)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    info = unwrap_dict(result)
    # 成功但空对象，当成查不到
    if not info:
        return "没有查到这个群的信息。"
    lines = [
        f"群名：{info.get('group_name') or ''}",
        f"人数：{info.get('member_count') or 0}/{info.get('max_member_count') or 0}",
        f"全员禁言：{'开' if info.get('group_all_shut') else '关'}",
    ]
    remark = info.get("group_remark") or ""
    # 有群备注时补一行，方便对上群里看到的备注名
    if remark:
        lines.append(f"备注：{remark}")
    owner = await _query_owner(event, config, group_id)
    # 群主拿不到就不占一行，get_group_info 本身不含这个字段
    if owner:
        lines.append(f"群主：{owner}")
    return "\n".join(lines)


async def _query_owner(event: object, config: object, group_id: object) -> str:
    """群主 QQ 号。get_group_info 不返回群主，要另调 detail 接口取 ownerUin。"""
    ok, result, _err = await call_action(event, config, "get_group_detail_info", group_id=group_id)
    # 取不到就返回空，不影响群信息其余部分
    if not ok:
        return ""
    detail = unwrap_dict(result)
    owner = detail.get("ownerUin")
    # 字段缺失时同样返回空
    if not owner:
        return ""
    return str(owner)


async def read_notice(event: object, config: object, limit: int) -> str:
    """读群公告。协议端按发布时间倒序给，这里只取前几条。"""
    group_id, err = await guard_readonly(event, config)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "_get_group_notice", group_id=group_id)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    notices = unwrap_list(result)
    # 这个群还没发过公告
    if not notices:
        return "本群没有公告。"
    want = _notice_limit(limit)
    lines = []
    for item in notices:
        # 要够了就停，避免一次塞太多
        if len(lines) >= want:
            break
        # 非 dict 的脏数据跳过
        if not isinstance(item, dict):
            continue
        lines.append(_format_notice(item))
    # 全是脏数据时按没有公告处理
    if not lines:
        return "本群没有公告。"
    return f"最近 {len(lines)} 条公告：\n" + "\n".join(lines)


def _notice_limit(limit: int) -> int:
    """把模型要的条数收进合理范围。"""
    parsed = parse_int(limit)
    # 没给或给的不合法时用默认条数
    if parsed is None:
        return NOTICE_SHOW_LIMIT
    # 要 0 条或负数没有意义，至少给 1 条
    if parsed < 1:
        return 1
    # 要太多会撑上下文，夹到上限
    if parsed > NOTICE_MAX_LIMIT:
        return NOTICE_MAX_LIMIT
    return parsed


def _format_notice(item: dict[str, object]) -> str:
    """一条公告收成时间 + 正文。正文里的 HTML 转义要还原成可读文本。"""
    ts = parse_int(item.get("publish_time"))
    sender = item.get("sender_id") or ""
    message = item.get("message")
    text = ""
    # 正常结构是 {message: {text: ...}}
    if isinstance(message, dict):
        text = str(message.get("text") or "")
    # 少数实现直接把 message 写成字符串
    elif message is not None:
        text = str(message)
    text = clip_text(html.unescape(text).strip(), NOTICE_TEXT_LIMIT)
    # 时间缺失时不硬编时间，直接说明未知
    when = format_ts(ts) if ts else "时间未知"
    nid = item.get("notice_id") or ""
    line = f"[{when}] {sender}"
    # 删公告时要用 notice_id
    if nid:
        line += f"  id {nid}"
    return f"{line}\n{text}"


async def send_notice(event: object, config: object, content: str, pinned: bool) -> str:
    """发群公告。需要机器人是本群管理员。"""
    # 配置关掉公告发布时直接拒绝
    if not get_bool(config, "allow_notice", True):
        return "发布公告已被插件配置禁用。"
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    text = (content or "").strip()
    # 空公告发出去只会占版面
    if not text:
        return "公告内容不能为空。"
    ok, _result, api_err = await call_action(
        event,
        config,
        "_send_group_notice",
        group_id=group_id,
        content=text,
        pinned=1 if pinned else 0,
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return "公告已发布。"


async def delete_notice(event: object, config: object, notice_id: str, group_id: str = "") -> str:
    """按公告 id 删除。id 来自 group_notice_list。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    nid = (notice_id or "").strip()
    # 空 id 协议端会失败
    if not nid:
        return "公告 id 不能为空。请先用 group_notice_list 查看。"
    ok, _result, api_err = await call_action(
        event, config, "_del_group_notice", group_id=target, notice_id=nid
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已删除公告 {nid}。"


async def list_bans(event: object, config: object) -> str:
    """查本群当前被禁言的成员。"""
    group_id, err = await guard_readonly(event, config)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "get_group_shut_list", group_id=group_id)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = unwrap_list(result)
    # 空列表说明当前没人被禁言
    if not items:
        return "本群当前没有被禁言的成员。"
    lines = []
    for item in items:
        # 空元素没法展示，跳过，免得把 None 念给模型
        if item is None:
            continue
        lines.append(_format_ban(item))
    # 过滤后什么都没剩，按没人被禁言处理
    if not lines:
        return "本群当前没有被禁言的成员。"
    return f"禁言中 {len(lines)} 人：\n" + "\n".join(lines)


def _format_ban(item: object) -> str:
    """一条禁言记录。协议端字段可能变化，取不到就退回原始字符串。"""
    # 不是 dict 就没法按字段取，原样展示
    if not isinstance(item, dict):
        return str(item)
    uid = item.get("user_id", "")
    nick = item.get("nickname", "")
    line = f"QQ {uid}  昵称 {nick}"
    ts = parse_int(item.get("shut_up_time"))
    # 有解禁时间就附上，方便判断还剩多久
    if ts:
        line += f"  解禁时间 {format_ts(ts)}"
    return line
