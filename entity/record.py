# 实体层：一条群聊记录。只描述数据形状，不负责存取。


class ChatRecord:
    """库里的一条群消息，给总结工具按时间正序展示。"""

    def __init__(self, ts: int, name: str, uid: str, text: str, message_id: str = "") -> None:
        # ts 是入库时的 Unix 秒，展示时再格式化。
        self.ts = ts
        self.name = name
        self.uid = uid
        self.text = text
        # 协议端的消息 ID，撤回时要用。老记录没有这个字段，允许为空。
        self.message_id = message_id
