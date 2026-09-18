# astrbot_plugin_group_agent

AstrBot 插件：用自然语言管 QQ 群和好友（QQ 能力 Agent）。

面向 NapCat / Lagrange / LLOneBot 等 OneBot v11 协议端。模型自己决定调哪个工具，群友不用记指令。

> 「把张三禁言十分钟」→ 先按昵称查 QQ 号 → 再调禁言
>
> 「总结一下今天群里聊了什么」→ 读本地群聊库 → 交给模型整理

## 它做什么

AstrBot 负责连 QQ、跑 Agent、做 Function Calling。本插件补 QQ 能力这一层：

| 环节 | 谁负责 |
| --- | --- |
| 连协议端、收发 QQ 消息 | AstrBot `aiocqhttp` 适配器 |
| LLM 循环、多轮工具调用 | AstrBot Agent Runner |
| 群管 / 好友 / 精华 / OCR | 本插件 |
| 群聊记录落库和读取 | 本插件 |
| 操作权限、失败原因回填模型 | 本插件 |

## 工具

模型按需自动调用。名单、OCR、语音转写只给后续工具用，不要念给用户。

群管（当前群；AstrBot 管理员可填 `group_id`）：

| 工具 | 作用 |
| --- | --- |
| `group_ban` | 禁言或解除禁言。`duration_minutes=0` 表示解除，最长 30 天 |
| `group_ban_self` | 随机禁言自己 1～5 分钟。全员可用，只能禁自己 |
| `group_ban_all` | 开 / 关全员禁言 |
| `group_kick` | 踢人，可选拒绝再次加群 |
| `group_set_card` | 设置或清空群名片 |
| `group_member_query` | 按 QQ 号查人，或按昵称反查，或列出管理员 |
| `group_member_list` | 拉成员名单给后续工具用 |
| `group_chat_history` | 取本群最近聊天记录 |
| `group_info` / `group_notice_list` / `group_notice_send` | 群信息、公告 |
| `group_ban_list` | 当前禁言名单 |
| `group_recall` / `group_recall_recent` | 撤回 |
| `group_set_title` / `group_poke` | 头衔、戳一戳 |
| `group_join_list` / `group_join_handle` | 加群申请 |
| `group_set_admin` | 设置或取消管理员 |
| `group_set_name` | 改群名 |
| `group_essence_list` / `set` / `delete` | 精华消息 |
| `group_notice_delete` | 删公告（id 来自 `group_notice_list`） |
| `group_join_option` | 加群方式：任何人 / 验证 / 不允许 / 问题 |
| `group_invite_policy` | 成员邀请好友进群的策略 |
| `group_todo` | 设 / 完成 / 取消群待办 |
| `group_sign` / `group_signed_list` | 打卡、今日打卡名单 |
| `group_honor` | 群荣誉（龙王等） |
| `group_at_all_remain` | 还能 @全体 几次 |
| `ocr_image` | 图片 OCR（仅 Windows NapCat） |
| `ptt_text` | 语音转文字 |
| `msg_emoji_like` | 给消息贴表情，默认 76（赞） |

仅 AstrBot 管理员：

| 工具 | 作用 |
| --- | --- |
| `qq_group_list` | 机器人所在群 |
| `group_set_remark` | 机器人自己对群的备注 |
| `friend_list` | 好友名单，可按关键字筛 |
| `friend_set_remark` | 好友备注 |
| `friend_request_handle` | 处理加好友请求 |
| `doubt_friend_list` / `handle` | 可疑好友申请 |
| `send_like` | 点赞 |
| `stranger_info` | 陌生人资料 |
| `qq_recent_contact` | 最近会话 |

指令：

- `/禁言自己`：全员可用，随机禁言自己 1～5 分钟（精确到秒）。群主/管理员无法被 QQ 禁言。
- `/群管状态`：看本群记了多少条。

## 安装

AstrBot ≥ 4.13，平台选 OneBot v11（aiocqhttp）。无第三方 Python 依赖。

```bash
cd AstrBot/data/plugins
git clone https://github.com/w1ndys/astrbot_plugin_group_agent
```

WebUI 插件页启用或点「重载插件」。

## 使用前

1. 机器人必须是该 QQ 群的管理员。
2. 你自己是群主 / 群管理员，或把 UID 加进 AstrBot 管理员列表（`/sid` 里的 UID，不是 UMO）。
3. 模型必须支持 Function Calling。建议打开「显示工具调用状态」，确认有没有真的调工具。
4. 在**群里**测群管。AstrBot 管理员私聊可用好友工具，以及填了群号的群能力。
5. 群里 `@机器人` 再说自然语言；如果唤醒前缀是 `/`，也可以 `/` 开头。

建议先测只读，再测会改群的动作：

```
@机器人 按「班级-姓名」检查这个群的群昵称，不合规的重置并警告
@机器人 查一下群 123456 里群昵称不合规的人，改掉并在群里提醒
@机器人 帮我查一下群里昵称带「某某」的成员 QQ 号
@机器人 总结一下这个群最近 1 小时都在聊什么
@机器人 把我的群名片改成「测试中」
@机器人 把 QQ 号 123456789 禁言 1 分钟
```

通了的标志：群里真的发生了改名片 / 禁言，并且 AstrBot 日志里有 `group_member_query`、`group_ban` 这些工具名。如果只是口头答应、日志没有工具调用，换一个支持 Function Calling 的模型。

## 配置

在 WebUI 插件配置里改，对应 `_conf_schema.json`：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `operator_mode` | `group_admin` | `group_admin`：QQ 群管或 AstrBot 管理员；`astrbot_admin`：仅后台管理员；`everyone`：所有人（危险） |
| `enable_history` | `true` | 是否记录群消息 |
| `history_operator_only` | `true` | 聊天记录只给有权限的人看 |
| `retention_days` | `30` | 记录保留天数 |
| `summary_max_messages` | `300` | 单次总结最多返回条数 |
| `allow_kick` / `allow_ban_all` | `true` | 踢人、全员禁言的总开关 |

## 工作原理（简要）

工具把结果 **return 给模型**，不直接 `yield` 到群里。这样才能「先查 QQ 号，再拿这个号去禁言」。协议端报错也会收成中文回填，Agent 循环不会断。

群聊记录是自己落库的。AstrBot 会话上下文只保留唤醒过机器人的消息，且有轮数上限，不能当聊天记录库。本插件监听全部群消息，写入 `data/plugin_data/astrbot_plugin_group_agent/group_history.db`。图片、语音只记占位符。

普通群员唤醒机器人时，会在请求模型前从工具列表摘掉 `group_ban`、好友列表等。模型看不到这些函数，就不会去调。工具函数里仍有鉴权，作为第二道。`group_ban_self` 是例外，群里全员可见，但只能禁发言人自己。好友和机器人所在群只有 AstrBot 管理员能看。

## 限制

- 只记录机器人运行期间收到的消息。离线期间没有。机器人自己发出的消息也不会入库。
- OCR 仅 Windows NapCat 可用。语音转写依赖协议端。
- 必须 Function Calling。
- 不能禁言或踢群主；单次禁言最多 30 天。
- 只支持 OneBot v11。QQ 官方 bot、Telegram 等不可用。

`/群管状态` 显示本群 0 条时，先看 AstrBot 是否开了 ID 白名单却没把该群放进去，以及群消息有没有进 AstrBot 日志。

## 安全

- 保持 `operator_mode = group_admin`，不要改成 `everyone`。
- `history_operator_only` 建议保持开启。
- 普通群员 `@` 机器人时，禁言/踢人等工具不会进本次模型请求；管理员唤醒时仍会带上。
- 不要把 NapCat 端口暴露到公网。
- 禁言和踢人会真实生效。建议先对小号测短时间禁言。

## 许可

AGPL-3.0（与 AstrBot 一致）。
