# 业务层：禁言、踢人、改名片。返回给模型看的中文。

from ..entity.constants import DEFAULT_BAN_MINUTES, MAX_BAN_SECONDS, ROLE_OWNER
from .auth import get_role, guard, self_id_of
from .onebot import call_action
from .parse import parse_int
from .settings import get_bool


async def ban_member(
    event: object, config: object, user_id: str, duration_minutes: object, reason: str
) -> str:
    """禁言或解除禁言。duration 为 0 表示解除。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就原样把原因回给模型
    if err:
        return err
    target = parse_int(user_id)
    # 模型常把昵称塞进 user_id，这里拦住并提示先去查号
    if target is None:
        return (
            f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号，"
            "可以先用 group_member_query 按昵称查到 QQ 号。"
        )
    # 禁言自己没有意义，协议端行为也不统一
    if str(target) == self_id_of(event):
        return "不能对自己执行禁言操作。"
    seconds, err = _ban_seconds(duration_minutes)
    # 时长不合法（超过 30 天）时不要发出协议请求
    if err:
        return err
    role = await get_role(event, config, group_id, str(target))
    # 群主不能被禁言，提前拦比等协议报错更清楚
    if role == ROLE_OWNER:
        return "不能禁言群主。"
    ok, _data, api_err = await call_action(
        event, config, "set_group_ban", group_id=group_id, user_id=target, duration=seconds
    )
    # 协议失败把原因回填，让模型自己解释或换人
    if not ok:
        return api_err
    # 0 秒是解除禁言，和「禁言 N 分钟」用不同话术
    if seconds == 0:
        msg = f"已解除 {target} 的禁言。"
    # 大于 0 秒就是禁言，把秒换回分钟给模型看
    else:
        minutes = seconds / 60
        msg = f"已禁言 {target} {minutes:g} 分钟。"
    # 有原因就附上，方便群友知道为什么
    if reason:
        msg += f"原因：{reason}"
    return msg


def _ban_seconds(duration_minutes: object) -> tuple[int, str]:
    """把模型给的分钟数收成秒。负数当解除禁言。超 30 天拒绝。"""
    parsed = parse_int(duration_minutes)
    # 不是整数时再试 float，再不行用默认 10 分钟
    if parsed is None:
        try:
            minutes = float(str(duration_minutes))
        except (TypeError, ValueError):
            minutes = float(DEFAULT_BAN_MINUTES)
    # 已经是整数就直接当分钟用
    else:
        minutes = float(parsed)
    seconds = max(int(minutes * 60), 0)
    # QQ 单次禁言上限 30 天，超了协议端也会拒
    if seconds > MAX_BAN_SECONDS:
        return 0, (
            f"禁言时长超过上限。QQ 单次禁言最多 30 天（43200 分钟），你请求的是 {minutes:g} 分钟。"
        )
    return seconds, ""


async def ban_all(event: object, config: object, enable: bool) -> str:
    """开启或关闭全员禁言。"""
    # 配置关掉全员禁言时，连 AstrBot 管理员也不能用
    if not get_bool(config, "allow_ban_all", True):
        return "全员禁言功能已被插件配置禁用。"
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    ok, _data, api_err = await call_action(
        event, config, "set_group_whole_ban", group_id=group_id, enable=bool(enable)
    )
    # 协议失败回填原因
    if not ok:
        return api_err
    # enable 真假对应开/关两套话术
    if enable:
        return "已开启全员禁言。"
    return "已解除全员禁言。"


async def kick_member(
    event: object, config: object, user_id: str, reject_add_request: bool, reason: str
) -> str:
    """把成员移出本群。"""
    # 配置关掉踢人时直接拒绝，避免误踢
    if not get_bool(config, "allow_kick", True):
        return "踢人功能已被插件配置禁用。"
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    target = parse_int(user_id)
    # 踢人必须是纯数字 QQ 号
    if target is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    # 不能把机器人自己踢出去
    if str(target) == self_id_of(event):
        return "不能把自己移出群聊。"
    role = await get_role(event, config, group_id, str(target))
    # 群主踢不掉
    if role == ROLE_OWNER:
        return "不能移出群主。"
    ok, _data, api_err = await call_action(
        event,
        config,
        "set_group_kick",
        group_id=group_id,
        user_id=target,
        reject_add_request=bool(reject_add_request),
    )
    # 协议失败回填原因
    if not ok:
        return api_err
    msg = f"已将 {target} 移出本群。"
    # 勾了拒绝再加群时明确说出来
    if reject_add_request:
        msg += "已拒绝其再次加群。"
    # 有原因就附上
    if reason:
        msg += f"原因：{reason}"
    return msg


async def set_card(event: object, config: object, user_id: str, card: str) -> str:
    """设置或清空群名片。空字符串表示清空。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    target = parse_int(user_id)
    # 改名片必须是纯数字 QQ 号
    if target is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, _data, api_err = await call_action(
        event, config, "set_group_card", group_id=group_id, user_id=target, card=card or ""
    )
    # 协议失败回填原因
    if not ok:
        return api_err
    # 空名片表示清空，和设置要用不同话术
    if card:
        return f"已将 {target} 的群名片设为「{card}」。"
    return f"已清空 {target} 的群名片。"
