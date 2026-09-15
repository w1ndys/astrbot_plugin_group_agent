# 实体层：群管插件用到的固定值。不依赖 AstrBot，也不访问数据库。

# QQ 群主、管理员在 OneBot 成员信息里的 role 取值。
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"

# QQ 单次禁言上限是 30 天。
MAX_BAN_SECONDS = 30 * 24 * 60 * 60

# 模型没给时长时，默认禁言 10 分钟，避免误操作成永久。
DEFAULT_BAN_MINUTES = 10

# 大群拉全量成员会撑爆模型上下文，所以列表和展示都截断。
MEMBER_LIST_LIMIT = 200
MEMBER_SHOW_LIMIT = 30

# 消息链里非文本段的占位符，总结时至少能看出「这里发过图/语音」。
MESSAGE_PLACEHOLDERS = {
    "Image": "[图片]",
    "Record": "[语音]",
    "Video": "[视频]",
    "File": "[文件]",
    "Face": "[表情]",
    "Poke": "[戳一戳]",
    "Forward": "[合并转发]",
    "Nodes": "[合并转发]",
    "Node": "[合并转发]",
    "Music": "[音乐]",
    "Json": "[卡片]",
    "Markdown": "[富文本]",
}

# 协议端报错关键词 -> 给模型看的中文说明。按列表顺序匹配第一条。
ERROR_HINTS = [
    (
        ("NOT_ENOUGH_PERM", "PERMISSION", "PERM", "权限"),
        "机器人权限不足。请在 QQ 里把机器人设为该群的管理员。",
    ),
    (
        ("OWNER", "群主"),
        "不能对群主执行该操作。",
    ),
    (
        ("GROUP_NOT_FOUND", "群不存在", "NO_SUCH_GROUP"),
        "群号不存在，或机器人不在该群。",
    ),
    (
        ("USER_NOT_FOUND", "成员不存在", "NOT_GROUP_MEMBER"),
        "目标用户不是该群成员。",
    ),
]
