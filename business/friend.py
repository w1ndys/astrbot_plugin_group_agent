# 业务层：好友列表、备注、申请、点赞、陌生人、最近会话。号级能力。

from ..entity.constants import FRIEND_SHOW_LIMIT, LIKE_MAX_TIMES
from .auth import guard_admin
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import clip_text, parse_int


async def list_friends(event: object, config: object, keyword: str = "") -> str:
    """拉好友名单。可按昵称或备注筛。"""
    err = guard_admin(event)
    # 群管不能翻机器人的好友
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "get_friend_list", no_cache=True)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = [x for x in unwrap_list(result) if isinstance(x, dict)]
    needle = (keyword or "").strip().lower()
    # 有关键字就过滤
    if needle:
        items = [x for x in items if _friend_hit(x, needle)]
    # 一个都没有
    if not items:
        return "没有匹配的好友。" if needle else "好友列表是空的。"
    shown = items[:FRIEND_SHOW_LIMIT]
    lines = [_format_friend(x) for x in shown]
    head = f"好友 {len(items)} 人。以下仅供后续工具使用，不要念给用户"
    # 太多只给前 N
    if len(items) > FRIEND_SHOW_LIMIT:
        head += f"；只返回前 {FRIEND_SHOW_LIMIT} 人"
    return head + "。\n" + "\n".join(lines)


def _friend_hit(item: dict, needle: str) -> bool:
    """昵称、备注、QQ 号包含关键字。"""
    nick = str(item.get("nickname") or "").lower()
    remark = str(item.get("remark") or "").lower()
    uid = str(item.get("user_id") or "")
    return needle in nick or needle in remark or needle == uid


def _format_friend(item: dict) -> str:
    """一行好友。"""
    uid = item.get("user_id", "")
    nick = item.get("nickname") or ""
    remark = item.get("remark") or ""
    line = f"QQ {uid}  昵称 {nick}"
    # 有备注时带上
    if remark:
        line += f"  备注 {remark}"
    return line


async def set_remark(event: object, config: object, user_id: str, remark: str) -> str:
    """改好友备注。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    uid = parse_int(user_id)
    # 必须是纯数字 QQ 号
    if uid is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, _data, api_err = await call_action(
        event, config, "set_friend_remark", user_id=str(uid), remark=remark or ""
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    text = (remark or "").strip()
    # 空备注是清空
    if not text:
        return f"已清空 {uid} 的备注。"
    return f"已将 {uid} 的备注设为「{text}」。"


async def handle_friend_request(
    event: object, config: object, flag: str, approve: bool, remark: str = ""
) -> str:
    """处理加好友请求。flag 来自上报。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    text = (flag or "").strip()
    # 空 flag 协议端会失败
    if not text:
        return "flag 不能为空。"
    kwargs = {"flag": text, "approve": bool(approve)}
    # 同意时可以顺带备注
    if remark:
        kwargs["remark"] = remark
    ok, _data, api_err = await call_action(event, config, "set_friend_add_request", **kwargs)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 同意和拒绝用不同话术
    if approve:
        return f"已同意好友申请 {text}。"
    return f"已拒绝好友申请 {text}。"


async def list_doubt_friends(event: object, config: object) -> str:
    """可疑好友申请。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    ok, result, api_err = await call_action(
        event, config, "get_doubt_friends_add_request", count=20
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = [x for x in unwrap_list(result) if isinstance(x, dict)]
    # 没有可疑申请
    if not items:
        return "当前没有可疑好友申请。"
    lines = []
    for item in items:
        uid = item.get("user_id", "")
        nick = item.get("nickname") or ""
        flag = item.get("flag") or ""
        reason = item.get("reason") or ""
        lines.append(f"flag {flag}  QQ {uid}  昵称 {nick}  {reason}")
    return "可疑好友申请：\n" + "\n".join(lines)


async def handle_doubt_friend(event: object, config: object, flag: str, approve: bool) -> str:
    """处理可疑好友申请。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    text = (flag or "").strip()
    # 空 flag 协议端会失败
    if not text:
        return "flag 不能为空。"
    ok, _data, api_err = await call_action(
        event, config, "set_doubt_friends_add_request", flag=text, approve=bool(approve)
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 同意和拒绝用不同话术
    if approve:
        return f"已同意可疑好友申请 {text}。"
    return f"已拒绝可疑好友申请 {text}。"


async def send_like(event: object, config: object, user_id: str, times: int = 1) -> str:
    """给一个人点赞。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    uid = parse_int(user_id)
    # 必须是纯数字 QQ 号
    if uid is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    n = parse_int(times) or 1
    # 次数夹住，避免一次点爆
    if n < 1:
        n = 1
    if n > LIKE_MAX_TIMES:
        n = LIKE_MAX_TIMES
    ok, _data, api_err = await call_action(
        event, config, "send_like", user_id=str(uid), times=n
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已给 {uid} 点赞 {n} 次。"


async def stranger_info(event: object, config: object, user_id: str) -> str:
    """查陌生人资料。不要把全部字段念给用户。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    uid = parse_int(user_id)
    # 必须是纯数字 QQ 号
    if uid is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, result, api_err = await call_action(
        event, config, "get_stranger_info", user_id=str(uid), no_cache=True
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    info = unwrap_dict(result)
    # 空对象
    if not info:
        return "没有查到这个人的资料。"
    nick = info.get("nickname") or ""
    sex = info.get("sex") or ""
    age = info.get("age") or ""
    sign = clip_text(str(info.get("long_nick") or ""), 80)
    qid = info.get("qid") or ""
    line = f"QQ {uid}  昵称 {nick}  性别 {sex}  年龄 {age}"
    # 有 QID 时带上
    if qid:
        line += f"  QID {qid}"
    # 有签名时带上
    if sign:
        line += f"  签名 {sign}"
    return line


async def recent_contact(event: object, config: object, count: int = 10) -> str:
    """最近会话。"""
    err = guard_admin(event)
    # 号级能力
    if err:
        return err
    n = parse_int(count) or 10
    # 条数夹住
    if n < 1:
        n = 1
    if n > 30:
        n = 30
    ok, result, api_err = await call_action(event, config, "get_recent_contact", count=n)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = unwrap_list(result)
    # 空
    if not items:
        return "没有最近会话。"
    lines = [str(x)[:200] for x in items]
    return "最近会话（仅供后续工具使用，不要念给用户）：\n" + "\n".join(lines)
