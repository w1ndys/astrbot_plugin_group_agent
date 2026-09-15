# 业务层：专属头衔、戳一戳、加群申请。返回给模型看的中文。

from ..entity.constants import JOIN_REQUEST_SHOW_LIMIT
from .auth import guard
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import parse_int
from .settings import get_bool


async def set_title(event: object, config: object, user_id: str, title: str) -> str:
    """设置或清空专属头衔。空字符串表示清空。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    target = parse_int(user_id)
    # 头衔必须指定纯数字 QQ 号
    if target is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, _data, api_err = await call_action(
        event,
        config,
        "set_group_special_title",
        group_id=group_id,
        user_id=target,
        special_title=title or "",
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 空字符串是清空，和设置要用不同话术
    if title:
        return f"已将 {target} 的头衔设为「{title}」。"
    return f"已清空 {target} 的头衔。"


async def poke_member(event: object, config: object, user_id: str) -> str:
    """在本群戳一个人。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    target = parse_int(user_id)
    # 戳人也必须是纯数字 QQ 号
    if target is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, _data, api_err = await call_action(
        event,
        config,
        "send_poke",
        group_id=str(group_id),
        user_id=str(target),
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已戳 {target}。"


async def list_join_requests(event: object, config: object) -> str:
    """列出本群尚未处理的加群申请。flag 就是 request_id，同意/拒绝时要用。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "get_group_system_msg", count=50)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    data = unwrap_dict(result)
    raw = data.get("join_requests")
    items = unwrap_list(raw) if raw is not None else []
    pending = []
    for item in items:
        # 非 dict 跳过
        if not isinstance(item, dict):
            continue
        # 已处理的申请不再列出
        if item.get("checked"):
            continue
        # 只看本群，协议端会把机器人所在全部群的申请一起返回
        if str(item.get("group_id") or "") != str(group_id):
            continue
        pending.append(item)
        # 太多时截断，避免撑爆上下文
        if len(pending) >= JOIN_REQUEST_SHOW_LIMIT:
            break
    # 没有待处理申请时明确说
    if not pending:
        return "本群当前没有待处理的加群申请。"
    lines = [_format_join(item) for item in pending]
    return f"待处理加群申请 {len(pending)} 条：\n" + "\n".join(lines)


def _format_join(item: dict[str, object]) -> str:
    """一条加群申请。flag 必须给模型，同意/拒绝时要用。"""
    flag = item.get("request_id", "")
    uin = item.get("invitor_uin", "")
    nick = item.get("requester_nick") or item.get("invitor_nick") or ""
    msg = str(item.get("message") or "").strip()
    line = f"flag {flag}  QQ {uin}  昵称 {nick}"
    # 有验证消息时带上，方便判断是不是广告
    if msg:
        line += f"  验证：{msg}"
    return line


async def handle_join_request(
    event: object, config: object, flag: str, approve: bool, reason: str
) -> str:
    """同意或拒绝一条加群申请。flag 来自 list_join_requests。"""
    # 配置关掉审批时直接拒绝
    if not get_bool(config, "allow_join_request", True):
        return "处理加群申请已被插件配置禁用。"
    _group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    text = (flag or "").strip()
    # flag 空了协议端会报 No such request
    if not text:
        return "flag 不能为空。请先用 group_join_list 查看待处理申请。"
    ok, _data, api_err = await call_action(
        event,
        config,
        "set_group_add_request",
        flag=text,
        approve=bool(approve),
        reason=reason or " ",
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 同意和拒绝用不同话术
    if approve:
        return f"已同意加群申请 {text}。"
    return f"已拒绝加群申请 {text}。"
