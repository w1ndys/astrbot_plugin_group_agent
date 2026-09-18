# 业务层：群列表、管理员、群名、入群方式、待办、打卡、荣誉、@全体剩余。

from ..entity.constants import (
    GROUP_LIST_SHOW_LIMIT,
    HONOR_SHOW_LIMIT,
    INVITE_POLICIES,
    JOIN_ADD_TYPES,
)
from .auth import guard_admin, guard_group, guard_group_write
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import parse_int


async def list_groups(event: object, config: object) -> str:
    """列出机器人所在群。只有 AstrBot 管理员能看。"""
    err = guard_admin(event)
    # 号级能力，群管也不能翻
    if err:
        return err
    ok, result, api_err = await call_action(event, config, "get_group_list", no_cache=True)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = [x for x in unwrap_list(result) if isinstance(x, dict)]
    # 一个群都没有
    if not items:
        return "机器人当前不在任何群。"
    shown = items[:GROUP_LIST_SHOW_LIMIT]
    lines = [_format_group(item) for item in shown]
    head = f"所在群 {len(items)} 个。以下仅供后续工具使用，不要念给用户"
    # 太多只给前 N
    if len(items) > GROUP_LIST_SHOW_LIMIT:
        head += f"；只返回前 {GROUP_LIST_SHOW_LIMIT} 个"
    return head + "。\n" + "\n".join(lines)


def _parse_add_type(add_type: object) -> int | None:
    """把模型给的加群方式收成 1～4。"""
    raw = str(add_type or "").strip()
    kind = JOIN_ADD_TYPES.get(raw.lower())
    # 中文别名大小写不变，再试原样
    if kind is None:
        kind = JOIN_ADD_TYPES.get(raw)
    # 模型有时直接给数字
    if kind is None:
        n = parse_int(raw)
        if n in (1, 2, 3, 4):
            return n
    return kind


def _format_group(item: dict) -> str:
    """一行群：群号、群名、人数。"""
    gid = item.get("group_id", "")
    name = item.get("group_name") or ""
    count = item.get("member_count") or ""
    line = f"群 {gid}  {name}"
    # 有人数时带上，方便对上大群
    if count != "":
        line += f"  人数 {count}"
    return line


async def set_admin(
    event: object, config: object, user_id: str, enable: bool, group_id: str = ""
) -> str:
    """设置或取消群管理员。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    uid = parse_int(user_id)
    # 必须是纯数字 QQ 号
    if uid is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, _data, api_err = await call_action(
        event,
        config,
        "set_group_admin",
        group_id=target,
        user_id=str(uid),
        enable=bool(enable),
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 取消和设置用不同话术
    if enable:
        return f"已将 {uid} 设为管理员。"
    return f"已取消 {uid} 的管理员。"


async def set_group_name(
    event: object, config: object, group_name: str, group_id: str = ""
) -> str:
    """改群名。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    name = (group_name or "").strip()
    # 空群名协议端会失败
    if not name:
        return "群名不能为空。"
    ok, _data, api_err = await call_action(
        event, config, "set_group_name", group_id=target, group_name=name
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"群名已改为「{name}」。"


async def set_group_remark(
    event: object, config: object, remark: str, group_id: str = ""
) -> str:
    """改机器人自己对这个群的备注，不是群名。本群群主/管理员可用。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    gid = parse_int(target)
    # 解析失败就原样当群号
    if gid is None:
        gid = target
    ok, _data, api_err = await call_action(
        event, config, "set_group_remark", group_id=str(gid), remark=remark or ""
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    text = (remark or "").strip()
    # 空备注是清空
    if not text:
        return f"已清空群 {gid} 的备注。"
    return f"已将群 {gid} 的备注设为「{text}」。"


async def set_join_option(
    event: object,
    config: object,
    add_type: str,
    question: str = "",
    answer: str = "",
    group_id: str = "",
) -> str:
    """改加群方式。add_type 可以是数字或「任何人/验证/不允许/问题」。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    kind = _parse_add_type(add_type)
    # 对不上就停，避免乱改入群设置
    if kind is None:
        return "加群方式只能是：任何人、验证、不允许、问题（或 1/2/3/4）。"
    kwargs = {"group_id": target, "add_type": kind}
    # 需要回答问题时才带问题和答案
    if question:
        kwargs["group_question"] = question
    if answer:
        kwargs["group_answer"] = answer
    ok, _data, api_err = await call_action(event, config, "set_group_add_option", **kwargs)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已修改加群方式（{add_type}）。"


async def set_invite_policy(
    event: object, config: object, policy: str, group_id: str = ""
) -> str:
    """改成员邀请好友进群的策略。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    raw = str(policy or "").strip()
    kind = INVITE_POLICIES.get(raw.lower()) or INVITE_POLICIES.get(raw)
    # 对不上就停
    if kind is None:
        return "策略只能是：禁止、审核、无需审核、百人以下无需审核。"
    ok, _data, api_err = await call_action(
        event, config, "set_group_member_invite_policy", group_id=target, policy=kind
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return f"已修改邀请策略（{kind}）。"


async def group_todo(
    event: object, config: object, action: str, message_id: str, group_id: str = ""
) -> str:
    """设/完成/取消群待办。message_id 来自聊天记录。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    act = (action or "").strip().lower()
    names = {"set": "set_group_todo", "complete": "complete_group_todo", "cancel": "cancel_group_todo"}
    # 只认这三个动作
    if act not in names:
        return "action 只能是 set、complete 或 cancel。"
    mid = (message_id or "").strip().lstrip("#")
    # 设待办必须有消息 ID
    if not mid:
        return "message_id 不能为空。"
    ok, _data, api_err = await call_action(
        event, config, names[act], group_id=target, message_id=mid
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    words = {"set": "已设为待办", "complete": "已完成待办", "cancel": "已取消待办"}
    return f"{words[act]}：{mid}。"


async def group_sign(event: object, config: object, group_id: str = "") -> str:
    """本群打卡。"""
    target, err = await guard_group_write(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    ok, _data, api_err = await call_action(event, config, "send_group_sign", group_id=str(target))
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    return "已打卡。"


async def signed_list(event: object, config: object, group_id: str = "") -> str:
    """今日打卡名单。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(
        event, config, "get_group_signed_list", group_id=target
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    items = unwrap_list(result)
    # 空名单
    if not items:
        return "今天还没有人打卡。"
    return f"今日打卡 {len(items)} 人：\n" + "\n".join(str(x) for x in items[:50])


async def honor_info(event: object, config: object, kind: str = "all", group_id: str = "") -> str:
    """查群荣誉。默认全部类型。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    honor_type = (kind or "all").strip() or "all"
    ok, result, api_err = await call_action(
        event, config, "get_group_honor_info", group_id=str(target), type=honor_type
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    data = unwrap_dict(result)
    # 空对象
    if not data:
        return "没有查到荣誉信息。"
    return _format_honor(data)


def _format_honor(data: dict) -> str:
    """荣誉只摘龙王和各榜前几人，避免整表塞进上下文。"""
    lines = []
    current = data.get("current_talkative")
    # 当前龙王单独一行
    if isinstance(current, dict):
        lines.append("当前龙王：" + _honor_person(current))
    mapping = (
        ("talkative_list", "龙王榜"),
        ("performer_list", "群聊之火"),
        ("legend_list", "群聊炽热"),
        ("emotion_list", "快乐源泉"),
        ("strong_newbie_list", "冒尖小春笋"),
    )
    for key, title in mapping:
        rows = data.get(key)
        # 没有这个榜就跳过
        if not isinstance(rows, list) or not rows:
            continue
        people = [_honor_person(x) for x in rows[:HONOR_SHOW_LIMIT] if isinstance(x, dict)]
        # 这一榜全是脏数据
        if people:
            lines.append(f"{title}：{'；'.join(people)}")
    # 一个字段都没有
    if not lines:
        return "没有查到荣誉信息。"
    return "\n".join(lines)


def _honor_person(item: dict) -> str:
    """荣誉条目上的人和描述。"""
    uid = item.get("user_id") or item.get("uin") or ""
    nick = item.get("nickname") or item.get("name") or ""
    desc = item.get("description") or item.get("day_count") or ""
    text = f"{nick}({uid})"
    # 有天数或说明时带上
    if desc != "":
        text += f" {desc}"
    return text


async def at_all_remain(event: object, config: object, group_id: str = "") -> str:
    """本群还能 @全体 几次。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(
        event, config, "get_group_at_all_remain", group_id=str(target)
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    data = unwrap_dict(result)
    remain = data.get("remain_at_all_count_for_group")
    self_remain = data.get("remain_at_all_count_for_uin")
    can = data.get("can_at_all")
    return (
        f"能否@全体：{can}；本群剩余 {remain} 次；"
        f"这个号剩余 {self_remain} 次。"
    )
