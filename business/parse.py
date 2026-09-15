# 业务层：把模型给的字符串收成数字/开关，以及把消息链收成可入库文本。

from datetime import datetime, timedelta, timezone

from ..entity.constants import MESSAGE_PLACEHOLDERS

# 展示时间用东八区，和国内群友的直觉一致。
_TZ_SHANGHAI = timezone(timedelta(hours=8))


def parse_int(raw: object) -> int | None:
    """把模型给的 QQ 号/时长收成整数。带空格或小数点时尽量救回来。"""
    # None 不是合法 ID
    if raw is None:
        return None
    text = str(raw).strip()
    # 空字符串不是合法 ID
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    # 模型有时会给 10.0 这种时长
    try:
        return int(float(text))
    except ValueError:
        return None


def format_ts(ts: int) -> str:
    """把入库的 Unix 秒格式化成群友能看懂的时间。"""
    dt = datetime.fromtimestamp(ts, tz=_TZ_SHANGHAI)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def hours_ago_ts(hours: float) -> int:
    """当前时刻往前推 N 小时，得到查询起点的 Unix 秒。"""
    now = datetime.now(tz=_TZ_SHANGHAI)
    start = now - timedelta(hours=hours)
    return int(start.timestamp())


def clip_text(text: str, limit: int) -> str:
    """超长消息截断后再入库，避免一条消息占满库和上下文。"""
    # 限额非法时不去截，免得把正常消息截成空
    if limit <= 0:
        return text
    # 没超限就原样入库
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def render_message(event: object) -> str:
    """把消息链收成一行文本。纯文本原样留下，图片/语音换成占位符。"""
    parts = []
    chain = getattr(event, "message_obj", None)
    # 没有消息对象时退回 get_message_str，至少能记下一句纯文本
    if chain is None:
        getter = getattr(event, "get_message_str", None)
        # 连纯文本接口都没有，只能记空
        if getter is None:
            return ""
        return str(getter() or "")

    items = getattr(chain, "message", None)
    # 消息对象里没有段列表时，同样退回纯文本
    if items is None:
        getter = getattr(event, "get_message_str", None)
        # 纯文本接口也没有就记空
        if getter is None:
            return ""
        return str(getter() or "")

    for item in items:
        piece = _render_one(item)
        # 空段不拼进去，避免连续空格
        if piece:
            parts.append(piece)
    return "".join(parts).strip()


def _render_one(item: object) -> str:
    """渲染单个消息段。"""
    name = type(item).__name__
    # 文本段优先取 text 字段
    if name in ("Plain", "PlainMessage", "Text"):
        return str(getattr(item, "text", "") or "")
    placeholder = MESSAGE_PLACEHOLDERS.get(name)
    # 图片/语音等用占位符，总结时还能看出发过什么
    if placeholder is not None:
        return placeholder
    # 未知类型再试 text，实在没有就丢掉，避免把对象地址写进库
    text = getattr(item, "text", None)
    # 未知类型里若还有 text 就留下文本
    if text:
        return str(text)
    return ""
