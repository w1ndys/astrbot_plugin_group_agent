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

# 群公告常常是整篇 HTML 文本，展示前截断，避免撑爆上下文。
NOTICE_TEXT_LIMIT = 400
# 一次默认展示几条公告，以及模型最多能要几条。
NOTICE_SHOW_LIMIT = 3
NOTICE_MAX_LIMIT = 10

# 一次最多撤回几条。撤回是群里可见的动作，条数要夹住。
RECALL_RECENT_MAX = 10

# 加群申请一次展示几条，避免把别的群的申请塞进上下文。
JOIN_REQUEST_SHOW_LIMIT = 10

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

# 协议端报错关键词 -> 给模型看的短中文。按列表顺序匹配第一条。
# 命中后不要再附带英文异常原文，否则模型会把原文念给群友。
ERROR_HINTS = [
    (
        ("CANNOT BAN ADMIN", "BAN ADMIN", "cannot ban admin"),
        "做不到，对方是管理员。",
    ),
    (
        ("CANNOT KICK ADMIN", "KICK ADMIN", "cannot kick admin"),
        "做不到，对方是管理员。",
    ),
    (
        ("NOT_ENOUGH_PERM", "PERMISSION", "PERM", "权限"),
        "机器人权限不足。",
    ),
    (
        ("OWNER", "群主"),
        "做不到，对方是群主。",
    ),
    (
        ("GROUP_NOT_FOUND", "群不存在", "NO_SUCH_GROUP"),
        "群号不存在，或机器人不在该群。",
    ),
    (
        ("USER_NOT_FOUND", "成员不存在", "NOT_GROUP_MEMBER"),
        "目标用户不是该群成员。",
    ),
    (
        ("RECALL FAILED",),
        "撤回失败：消息太旧，协议端已经忘了它的 ID，或它已被撤回。",
    ),
]
