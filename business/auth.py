# 业务层：谁能用群管工具。默认必须是 QQ 群管或 AstrBot 管理员。

from ..entity.constants import ROLE_ADMIN, ROLE_OWNER
from .onebot import call_action, unwrap_dict
from .parse import parse_int
from .settings import get_setting


def is_astrbot_admin(event: object) -> bool:
    """当前发言人是不是 AstrBot 后台里配置的管理员。"""
    checker = getattr(event, "is_admin", None)
    # 没有这个方法就当不是，避免误放行
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def group_id_of(event: object) -> object:
    """从事件里取出群号。私聊没有群号，调用方要自己拒绝。"""
    raw = event.get_group_id()  # type: ignore[union-attr]
    parsed = parse_int(raw)
    # 解析失败时原样传给协议端，兼容非纯数字群号
    if parsed is None:
        return raw
    return parsed


def self_id_of(event: object) -> str:
    """机器人自己的 QQ 号，用来拦住「禁言自己」「踢自己」。"""
    getter = getattr(event, "get_self_id", None)
    # 没有 get_self_id 时返回空，后面的自禁言检查会自然跳过
    if getter is None:
        return ""
    return str(getter() or "")


async def get_role(event: object, config: object, group_id: object, user_id: str) -> str:
    """查一个人在本群的角色。查不到就当普通成员。"""
    ok, result, _err = await call_action(
        event,
        config,
        "get_group_member_info",
        group_id=group_id,
        user_id=parse_int(user_id) or user_id,
        no_cache=True,
    )
    # 协议失败时不能当成管理员，否则权限检查会被绕过
    if not ok:
        return ""
    info = unwrap_dict(result)
    return str(info.get("role") or "")


async def check_operator(event: object, config: object, group_id: object) -> str:
    """调用者有没有资格用群管工具。空字符串表示通过，否则是拒绝原因。"""
    mode = str(get_setting(config, "operator_mode", "group_admin") or "group_admin")
    # everyone 是危险开关，只在配置里明确打开时才放行
    if mode == "everyone":
        return ""
    # AstrBot 管理员始终可以操作，不看 QQ 群角色
    if is_astrbot_admin(event):
        return ""
    # 配置成只认 AstrBot 管理员时，群管身份也不够
    if mode == "astrbot_admin":
        return "只有 AstrBot 管理员能执行该操作。"
    sender = str(event.get_sender_id())  # type: ignore[union-attr]
    role = await get_role(event, config, group_id, sender)
    # QQ 群主或管理员才放行
    if role in (ROLE_OWNER, ROLE_ADMIN):
        return ""
    return "你不是本群管理员，也不是 AstrBot 管理员，不能执行群管操作。"


async def check_bot_admin(event: object, config: object, group_id: object) -> str:
    """机器人自己是不是本群管理员。不是的话协议端多半也会失败，提前说明更清楚。"""
    bot_id = self_id_of(event)
    # 拿不到自身 ID 时不拦，把问题留给协议端报错
    if not bot_id:
        return ""
    role = await get_role(event, config, group_id, bot_id)
    # 机器人必须是本群管理员，否则协议端多半失败
    if role in (ROLE_OWNER, ROLE_ADMIN):
        return ""
    return "机器人不是本群管理员，无法执行该操作。请在 QQ 里把机器人设为管理员。"


async def guard(event: object, config: object) -> tuple[object, str]:
    """群管动作的统一入口检查：必须在群里，调用者和机器人都有权限。"""
    group_id = group_id_of(event)
    # 私聊没有群号，禁言/踢人没有对象群
    if not group_id:
        return None, "该操作只能在群聊中使用。"
    err = await check_operator(event, config, group_id)
    # 调用者没权限就停，不继续查机器人身份
    if err:
        return None, err
    err = await check_bot_admin(event, config, group_id)
    # 机器人没权限也停，给模型一句人话而不是协议报错
    if err:
        return None, err
    return group_id, ""


async def guard_readonly(event: object, config: object) -> tuple[object, str]:
    """只读动作的检查：必须在群里，调用者有权限即可，不要求机器人是管理员。"""
    group_id = group_id_of(event)
    # 私聊没有群号，读不到群信息
    if not group_id:
        return None, "该操作只能在群聊中使用。"
    err = await check_operator(event, config, group_id)
    # 调用者没权限就不放行，群信息和公告同样涉及群内隐私
    if err:
        return None, err
    return group_id, ""
