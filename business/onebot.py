# 业务层：调用 OneBot v11。异常一律收成中文，不往上抛，免得打断 Agent 循环。

import asyncio

from ..entity.constants import ERROR_HINTS
from .settings import get_int


def _extract_wording(text: str) -> str:
    """从 ActionFailed 字符串里抽出 wording='...' 这一小段。"""
    key = "wording='"
    start = text.find(key)
    # 没有 wording 字段就放弃
    if start < 0:
        return ""
    start += len(key)
    end = text.find("'", start)
    # 引号不配对时放弃，避免切出一长串
    if end < 0:
        return ""
    return text[start:end]


def explain_error(exc: BaseException) -> str:
    """把协议端异常收成模型能看懂的中文。按关键词匹配第一条提示。"""
    text = str(exc)
    upper = text.upper()
    for keys, hint in ERROR_HINTS:
        for key in keys:
            # 英文关键词忽略大小写；中文关键词用原文比
            if key.isascii():
                hit = key.upper() in upper
            # 中文关键词按原文匹配，不能 upper
            else:
                hit = key in text
            # 命中第一条提示就返，不再附带英文原文
            if hit:
                return hint
    wording = _extract_wording(text)
    # 协议端带了 wording 时，用它当短原因，不要整段 ActionFailed
    if wording:
        return "做不到：" + wording
    return "协议端调用失败。"


async def call_action(
    event: object, config: object, action: str, **kwargs: object
) -> tuple[bool, object, str]:
    """调协议端一个动作。成功返回 (True, 数据, "")，失败返回 (False, None, 原因)。"""
    bot = getattr(event, "bot", None)
    # 没有 bot 说明当前事件不是 OneBot，群管工具不能用
    if bot is None:
        return False, None, "当前平台没有 bot 对象，本插件只支持 OneBot v11。"
    api = getattr(bot, "api", None)
    # 有 bot 但没有 api 同样不能调协议端
    if api is None:
        return False, None, "当前 bot 没有 api，无法调用 OneBot 动作。"
    timeout = get_int(config, "api_timeout", 15)
    try:
        result = await asyncio.wait_for(api.call_action(action, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        return False, None, f"协议端调用超时（{timeout} 秒）：{action}"
    except Exception as exc:
        return False, None, explain_error(exc)
    return True, result, ""


def unwrap_list(result: object) -> list[object]:
    """OneBot 有的实现直接给列表，有的包在 data 字段里。统一抽成 list。"""
    # 直接就是列表的实现，原样返
    if isinstance(result, list):
        return result
    # 常见包装：{"data": [...]}
    if isinstance(result, dict):
        data = result.get("data")
        # data 也得真的是列表才用，避免把 dict 当成成员列表
        if isinstance(data, list):
            return data
    return []


def unwrap_dict(result: object) -> dict[str, object]:
    """成员信息同样可能包一层 data。"""
    # 不是 dict 就没法当成员信息
    if isinstance(result, dict):
        data = result.get("data")
        # 有 data 且 data 是 dict 时，用里层
        if isinstance(data, dict):
            return data
        return result
    return {}
