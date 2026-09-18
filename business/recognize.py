# 业务层：OCR、语音转文字、消息表情回复。给后续判断用，不要把全文贴群里。

from ..entity.constants import OCR_TEXT_LIMIT
from .auth import check_operator, group_id_of, guard_admin
from .onebot import call_action, unwrap_dict, unwrap_list
from .parse import clip_text, parse_int


async def _guard_media(event: object, config: object) -> str:
    """群里要有群管权限；私聊只有 AstrBot 管理员。"""
    gid = group_id_of(event)
    # 在群里按群管鉴权
    if gid:
        return await check_operator(event, config, gid)
    return guard_admin(event)


async def ocr_image(event: object, config: object, image: str) -> str:
    """识别图片文字。image 可以是路径、URL 或 file_id。"""
    err = await _guard_media(event, config)
    # 没过权限检查就停
    if err:
        return err
    src = (image or "").strip()
    # 空图没法认
    if not src:
        return "image 不能为空，填图片 URL、路径或 file_id。"
    ok, result, api_err = await call_action(event, config, "ocr_image", image=src)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    data = unwrap_dict(result)
    texts = data.get("texts")
    parts = []
    # 标准结构是 texts: [{text: ...}]
    if isinstance(texts, list):
        for item in texts:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item.get("text")))
            elif item:
                parts.append(str(item))
    blob = clip_text("\n".join(parts).strip() or str(data), OCR_TEXT_LIMIT)
    # 没认出字
    if not blob.strip():
        return "没有识别到文字。"
    return "OCR 结果（不要把全文贴到群里）：\n" + blob


async def ptt_text(event: object, config: object, message_id: str) -> str:
    """取一条语音消息的转写。"""
    err = await _guard_media(event, config)
    # 没过权限检查就停
    if err:
        return err
    mid = parse_int(str(message_id or "").lstrip("#"))
    # 必须是数字消息 ID
    if mid is None:
        return "message_id 必须是数字。"
    ok, result, api_err = await call_action(event, config, "fetch_ptt_text", message_id=mid)
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    data = unwrap_dict(result)
    text = data.get("text") or data.get("result") or ""
    # 有的实现直接回字符串
    if not text:
        items = unwrap_list(result)
        text = str(items[0]) if items else str(data)
    blob = clip_text(str(text).strip(), OCR_TEXT_LIMIT)
    # 空转写
    if not blob:
        return "没有转写出文字。"
    return "语音转文字（不要把全文贴到群里）：\n" + blob


async def emoji_like(
    event: object, config: object, message_id: str, emoji_id: str = "76", set_on: bool = True
) -> str:
    """给消息贴表情。默认 76（赞）。"""
    err = await _guard_media(event, config)
    # 没过权限检查就停
    if err:
        return err
    mid = parse_int(str(message_id or "").lstrip("#"))
    # 必须是数字消息 ID
    if mid is None:
        return "message_id 必须是数字。"
    eid = (emoji_id or "76").strip() or "76"
    ok, _data, api_err = await call_action(
        event,
        config,
        "set_msg_emoji_like",
        message_id=mid,
        emoji_id=eid,
        set=bool(set_on),
    )
    # 协议失败把原因回给模型
    if not ok:
        return api_err
    # 取消和贴上用不同话术
    if set_on:
        return f"已给消息 {mid} 贴表情 {eid}。"
    return f"已取消消息 {mid} 的表情 {eid}。"
