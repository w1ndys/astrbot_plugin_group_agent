# 业务层：查群成员。按 QQ 号、按昵称、列出管理员，或拉指定群名单。

from ..entity.constants import (
    MEMBER_LIST_LIMIT,
    MEMBER_LIST_SHOW_DEFAULT,
    MEMBER_SHOW_LIMIT,
    ROLE_ADMIN,
    ROLE_OWNER,
)
from .auth import guard, guard_group
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import parse_int


async def query_member(
    event: object,
    config: object,
    user_id: str,
    keyword: str,
    list_admins: bool,
) -> str:
    """查成员的总入口。三个参数至少要有一个。"""
    group_id, err = await guard(event, config)
    # 没过权限检查就停
    if err:
        return err
    # 列出管理员优先，避免和 keyword 同时传来时歧义
    if list_admins:
        return await _list_admins(event, config, group_id)
    # 有 QQ 号就按号查，最准确
    if user_id:
        return await _query_by_id(event, config, group_id, user_id)
    # 只给了昵称就反查 QQ 号
    if keyword:
        return await _query_by_keyword(event, config, group_id, keyword)
    return "请至少提供 user_id、keyword 或 list_admins 其中之一。"


async def list_members(
    event: object, config: object, group_id: str = "", limit: int = 0
) -> str:
    """拉指定群的成员名单给后续工具用。没填群号就用当前群。"""
    target, err = await guard_group(event, config, group_id)
    # 没过权限检查就停
    if err:
        return err
    ok, result, api_err = await call_action(
        event, config, "get_group_member_list", group_id=target
    )
    # 拉名单失败就停
    if not ok:
        return api_err
    items = [item for item in unwrap_list(result) if isinstance(item, dict)]
    # 空名单当成查不到，避免模型以为工具坏了
    if not items:
        return f"群 {target} 没有查到成员。"
    want = _list_show_limit(limit)
    shown = items[:want]
    lines = [_format_member(item) for item in shown]
    head = f"群 {target} 成员 {len(items)} 人。以下仅供后续工具使用，不要念给用户"
    # 人太多只给前 N，避免撑爆上下文
    if len(items) > want:
        head += f"；只返回前 {want} 人"
    return head + "。\n" + "\n".join(lines)


def _list_show_limit(limit: int) -> int:
    """名单展示人数夹在 1 和上限之间。"""
    # 模型没给或给了 0，用默认
    if not limit:
        return MEMBER_LIST_SHOW_DEFAULT
    n = int(limit)
    # 至少展示 1 人，否则这工具没意义
    if n < 1:
        return 1
    # 超过扫描上限就夹住
    if n > MEMBER_LIST_LIMIT:
        return MEMBER_LIST_LIMIT
    return n


def _format_member(info: dict[str, object]) -> str:
    """把一条成员信息收成模型好读的一行。"""
    uid = info.get("user_id", "")
    nick = info.get("nickname", "")
    card = info.get("card", "")
    role = info.get("role", "")
    title = info.get("title", "")
    line = f"QQ {uid}  昵称 {nick}"
    # 有群名片时带上，方便对上「群里叫什么」
    if card:
        line += f"  名片 {card}"
    # 角色用来判断能不能动手
    if role:
        line += f"  角色 {role}"
    # 头衔只是展示，不影响权限
    if title:
        line += f"  头衔 {title}"
    return line


async def _query_by_id(event: object, config: object, group_id: object, user_id: str) -> str:
    """按 QQ 号查一个人。"""
    target = parse_int(user_id)
    # 不是纯数字就不要发协议请求
    if target is None:
        return f"user_id 不合法：{user_id!r}。需要纯数字 QQ 号。"
    ok, result, api_err = await call_action(
        event,
        config,
        "get_group_member_info",
        group_id=group_id,
        user_id=target,
        no_cache=True,
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err or "没有查到该成员信息。"
    info = unwrap_dict(result)
    # 成功但空对象，当成没这个人
    if not info:
        return "没有查到该成员信息。"
    return "查到成员：\n" + _format_member(info)


async def _list_admins(event: object, config: object, group_id: object) -> str:
    """列出本群群主和管理员。"""
    ok, result, api_err = await call_action(
        event, config, "get_group_member_list", group_id=group_id
    )
    # 拉名单失败就停
    if not ok:
        return api_err
    lines = []
    for item in unwrap_list(result):
        # 非 dict 的脏数据跳过
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        # 只要群主和管理员，普通成员不列入
        if role not in (ROLE_OWNER, ROLE_ADMIN):
            continue
        lines.append(_format_member(item))
    # 一个都没有时明确说，避免模型以为工具坏了
    if not lines:
        return "没有查到管理员信息。"
    return "本群管理员：\n" + "\n".join(lines)


async def _query_by_keyword(event: object, config: object, group_id: object, keyword: str) -> str:
    """按昵称或群名片反查 QQ 号。大群只扫前 N 人。"""
    ok, result, api_err = await call_action(
        event, config, "get_group_member_list", group_id=group_id
    )
    # 拉名单失败就停
    if not ok:
        return api_err
    needle = keyword.strip().lower()
    hits = []
    scanned = 0
    for item in unwrap_list(result):
        scanned += 1
        # 大群截断，避免一次把几万人塞进内存
        if scanned > MEMBER_LIST_LIMIT:
            break
        # 非 dict 的脏数据跳过
        if not isinstance(item, dict):
            continue
        card = str(item.get("card") or "").lower()
        nick = str(item.get("nickname") or "").lower()
        # 名片或昵称包含关键字才算命中
        if needle in card or needle in nick:
            hits.append(item)
    # 一个都没命中，让模型换关键字或改用 QQ 号
    if not hits:
        return f"没有找到昵称或群名片包含「{keyword}」的群成员。"
    shown = hits[:MEMBER_SHOW_LIMIT]
    lines = []
    for item in shown:
        lines.append(_format_member(item))
    suffix = ""
    # 命中太多时只展示前 N 人，避免撑爆上下文
    if len(hits) > MEMBER_SHOW_LIMIT:
        suffix = f"\n（共 {len(hits)} 人，只展示前 {MEMBER_SHOW_LIMIT} 人）"
    return "匹配到：\n" + "\n".join(lines) + suffix
