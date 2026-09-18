# 入口层：向 AstrBot 注册 LLM 工具、群消息记录和状态指令。
# 真正的权限判断和协议调用在 business 里。发模型前会按权限摘掉工具。
#
# 工具必须 return str，不能 yield event.plain_result。
# yield 会把结果直接发给用户，模型拿到空结果，
# 「先查 QQ 号再禁言」这种两步操作就会断掉。

import asyncio
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .business.auth import tools_to_hide_before_llm
from .business.essence import delete_essence, list_essence, set_essence
from .business.friend import (
    handle_doubt_friend,
    handle_friend_request,
    list_doubt_friends,
    list_friends,
    recent_contact,
    send_like,
    set_remark,
    stranger_info,
)
from .business.group_extra import (
    at_all_remain,
    group_sign,
    group_todo,
    honor_info,
    list_groups,
    set_admin,
    set_group_name,
    set_group_remark,
    set_invite_policy,
    set_join_option,
    signed_list,
)
from .business.history import read_history
from .business.info import (
    delete_notice,
    list_bans,
    query_group_info,
    read_notice,
    send_notice,
)
from .business.member import (
    handle_join_request,
    list_join_requests,
    poke_member,
    set_title,
)
from .business.ops import ban_all, ban_member, ban_self, kick_member, set_card
from .business.parse import clip_text, render_message
from .business.query import list_members, query_member
from .business.recall import recall_one, recall_recent
from .business.recognize import emoji_like, ocr_image, ptt_text
from .business.settings import get_bool, get_int
from .data.store import HistoryStore
from .entity.constants import DEFAULT_BAN_MINUTES, NOTICE_SHOW_LIMIT, RECALL_RECENT_MAX


class GroupAgentPlugin(Star):
    """AstrBot QQ 能力插件。把自然语言收成 OneBot 群管和好友动作。"""

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self._config = config
        data_dir = Path(StarTools.get_data_dir())
        db_path = data_dir / "group_history.db"
        self.store = HistoryStore(db_path)
        logger.info("[group_agent] 群聊记录库已就绪：%s", db_path)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def initialize(self) -> None:
        """启动时关掉 AstrBot 自带的群历史工具，避免模型拿错 message_id。"""
        ok = await self.context.deactivate_llm_tool_async("get_group_message_history")
        # 关掉了才记一句，没找到工具也不当失败
        if ok:
            logger.info("[group_agent] 已停用内置工具 get_group_message_history")

    def _cfg_int(self, key: str, default: int) -> int:
        """入口里读整数配置的短封装。"""
        return get_int(self._config, key, default)

    def _cfg_bool(self, key: str, default: bool) -> bool:
        """入口里读开关配置的短封装。"""
        return get_bool(self._config, key, default)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req) -> None:
        """请求模型前：没权限则摘掉群管工具，有权限才补群管回复规则。"""
        tools = getattr(req, "func_tool", None)
        hidden = await tools_to_hide_before_llm(event, self._config)
        # 请求里还挂着内置历史工具时当场拿掉，避免模型再用错 ID
        if tools is not None and hasattr(tools, "remove_tool"):
            tools.remove_tool("get_group_message_history")
            for name in hidden:
                tools.remove_tool(name)
        extra = (
            "回复规则：只对用户说结果，一两句中文。"
            "不要说「我先查一下」。不要列一是二是三是。"
            "不要复述英文报错。"
            "不要用 get_group_message_history。"
            "名单、OCR、语音转写只给后续工具用，不要念给用户。"
        )
        # 群里才把禁言自己留给模型；闲聊不要调，私聊没有这个工具
        if "group_ban_self" not in hidden:
            extra += "只有用户明确要求禁言自己时才调用 group_ban_self，时长随机，不能指定别人。闲聊不要调。"
        if "group_ban" not in hidden:
            extra += (
                "已有 QQ 号就直接禁言，不要先查询。"
                "不能操作管理员时只说「做不到，对方是管理员」。"
                "查记录和撤回只用 group_chat_history / group_recall。"
                "撤回必须用记录里的 #数字。群名片和昵称可能不同，按 QQ 号认人。"
                "group_member_list 只给后续工具用，不要把名单念给用户。"
                "检查群昵称时先拉名单，不合规的用 group_set_card（card 填空即重置），"
                "警告写在最终回复里，不要贴名单。"
            )
        if "group_honor" not in hidden:
            extra += "指定群时可填 group_id。荣誉、打卡、精华、待办只在用户明确要求时调用。"
        if "friend_list" not in hidden:
            extra += "好友列表、所在群列表、点赞只有管理员能用，不要把名单念给用户。"
        if "group_ban" in hidden and "group_honor" in hidden and "friend_list" in hidden:
            extra += "不能禁言别人，也不要假装去禁。"
        sys_p = getattr(req, "system_prompt", None)
        # 没有 system_prompt 字段时接到 prompt 末尾
        if sys_p is None:
            req.prompt = str(getattr(req, "prompt", "") or "") + "\n" + extra
        # 有 system_prompt 就接到系统提示，模型更不容易漏看
        else:
            req.system_prompt = str(sys_p or "") + "\n" + extra

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        """被动记录每一条群消息。不唤醒机器人的话也要记下，否则总结会缺段。"""
        # 配置关了就一条都不写
        if not self._cfg_bool("enable_history", True):
            return
        group_id = event.get_group_id()
        # 没有群号就不是群消息，不入库
        if not group_id:
            return
        text = render_message(event)
        # 空消息（例如纯戳一戳解析失败）记一条占位，避免时间轴出现空洞
        if not text:
            text = "[空消息]"
        text = clip_text(text, self._cfg_int("max_text_len", 300))
        message_id = _event_message_id(event)
        try:
            await self.store.add(
                int(time.time()),
                str(group_id),
                str(event.get_sender_id()),
                event.get_sender_name() or "未知用户",
                text,
                message_id,
            )
        except Exception as exc:
            # 入库失败不能影响正常聊天
            logger.error("[group_agent] 记录群消息失败：%s", exc)

    @filter.llm_tool(name="group_ban")
    async def tool_group_ban(
        self,
        event: AstrMessageEvent,
        user_id: str,
        duration_minutes: float = DEFAULT_BAN_MINUTES,
        reason: str = "",
    ) -> str:
        """禁言或解除禁言某个群成员。已有纯数字 QQ 号时直接调用，不要先查询。
        对用户最终回复只要一句结果，不要预告、不要列方案。

        Args:
            user_id(string): 要操作的群成员 QQ 号，必须是纯数字
            duration_minutes(number): 禁言时长，单位为分钟；填 0 表示解除禁言；最大 43200
            reason(string): 禁言原因，仅用于向群友说明，可以为空
        """
        return await ban_member(event, self._config, user_id, duration_minutes, reason)

    @filter.llm_tool(name="group_ban_self")
    async def tool_group_ban_self(self, event: AstrMessageEvent) -> str:
        """随机禁言当前发言人自己 1 到 5 分钟（精确到秒）。只能禁自己，不能指定别人。
        对用户最终回复只要一句结果。
        """
        return await ban_self(event, self._config)

    @filter.llm_tool(name="group_ban_all")
    async def tool_group_ban_all(self, event: AstrMessageEvent, enable: bool = True) -> str:
        """开启或关闭全员禁言。

        Args:
            enable(boolean): true 表示开启全员禁言，false 表示解除全员禁言
        """
        return await ban_all(event, self._config, enable)

    @filter.llm_tool(name="group_kick")
    async def tool_group_kick(
        self,
        event: AstrMessageEvent,
        user_id: str,
        reject_add_request: bool = False,
        reason: str = "",
    ) -> str:
        """把某个群成员移出群聊（踢人）。

        Args:
            user_id(string): 要移出的群成员 QQ 号，必须是纯数字
            reject_add_request(boolean): 是否同时拒绝此人再次加群，默认 false
            reason(string): 操作原因，仅用于向群友说明，可以为空
        """
        return await kick_member(event, self._config, user_id, reject_add_request, reason)

    @filter.llm_tool(name="group_set_card")
    async def tool_group_set_card(
        self, event: AstrMessageEvent, user_id: str, card: str = ""
    ) -> str:
        """设置或清空某个群成员的群名片。

        Args:
            user_id(string): 要改名片的群成员 QQ 号，必须是纯数字
            card(string): 新的群名片；空字符串表示清空
        """
        return await set_card(event, self._config, user_id, card)

    @filter.llm_tool(name="group_member_query")
    async def tool_group_member_query(
        self,
        event: AstrMessageEvent,
        user_id: str = "",
        keyword: str = "",
        list_admins: bool = False,
    ) -> str:
        """查询群成员。只有不知道 QQ 号时才用；已经有 QQ 号就不要调用。
        对用户最终回复不要念出完整成员资料。

        Args:
            user_id(string): 要查询的 QQ 号，和 keyword、list_admins 三选一
            keyword(string): 昵称或群名片关键字，用来反查 QQ 号
            list_admins(boolean): true 时列出本群群主和管理员
        """
        return await query_member(event, self._config, user_id, keyword, list_admins)

    @filter.llm_tool(name="group_member_list")
    async def tool_group_member_list(
        self,
        event: AstrMessageEvent,
        group_id: str = "",
        limit: int = 200,
    ) -> str:
        """拉指定群成员名单，只给后续工具用，不要念给用户。
        没填群号时查当前群。检查群昵称是否合规时先调这个，
        再对不合规的人调 group_set_card（card 填空即重置），
        警告写在最终回复里，不要贴名单。不要改群主名片，除非用户明确要求。

        Args:
            group_id(string): 可选。要查的群号；不填则用当前群
            limit(number): 最多返回多少人，默认 200，最大 200
        """
        return await list_members(event, self._config, group_id, int(limit or 0))

    @filter.llm_tool(name="group_chat_history")
    async def tool_group_chat_history(
        self,
        event: AstrMessageEvent,
        hours: float = 24,
        max_messages: int = 200,
    ) -> str:
        """获取本群最近聊天记录。撤回前必须先调这个拿到 #消息ID。
        不要用 get_group_message_history，那个 ID 撤不了。
        群名片和昵称可能不同，按 QQ 号认人。

        Args:
            hours(number): 回溯多少小时，默认 24
            max_messages(number): 最多返回多少条，默认 200
        """
        return await read_history(self.store, event, self._config, hours, int(max_messages))

    @filter.llm_tool(name="group_info")
    async def tool_group_info(self, event: AstrMessageEvent) -> str:
        """查本群基本信息：群名、人数、上限、群主、是否全员禁言。
        对用户最终回复不要照念全部字段。

        Args: 无
        """
        return await query_group_info(event, self._config)

    @filter.llm_tool(name="group_notice_list")
    async def tool_group_notice_list(
        self, event: AstrMessageEvent, limit: int = NOTICE_SHOW_LIMIT
    ) -> str:
        """读本群公告。用户想看看群公告时用这个。

        Args:
            limit(number): 最多读几条，默认 3，最大 10
        """
        return await read_notice(event, self._config, int(limit))

    @filter.llm_tool(name="group_notice_send")
    async def tool_group_notice_send(
        self, event: AstrMessageEvent, content: str, pinned: bool = False
    ) -> str:
        """发布群公告。这是公开动作，全体群成员都会看到，只在用户明确要求时调用。
        对用户最终回复只要一句结果。

        Args:
            content(string): 公告正文，不能为空
            pinned(boolean): 是否置顶，默认 false
        """
        return await send_notice(event, self._config, content, pinned)

    @filter.llm_tool(name="group_ban_list")
    async def tool_group_ban_list(self, event: AstrMessageEvent) -> str:
        """查本群当前被禁言的成员名单。

        Args: 无
        """
        return await list_bans(event, self._config)

    @filter.llm_tool(name="group_recall")
    async def tool_group_recall(self, event: AstrMessageEvent, message_id: str) -> str:
        """撤回一条指定消息。message_id 必须是 group_chat_history 返回的 #数字。
        不要用其它历史工具给的 id。太旧会失败。对用户最终回复只要一句结果。

        Args:
            message_id(string): 要撤回的消息 ID，必须是数字
        """
        return await recall_one(event, self._config, message_id)

    @filter.llm_tool(name="group_recall_recent")
    async def tool_group_recall_recent(self, event: AstrMessageEvent, count: int = 1) -> str:
        """撤回本群最近若干条消息。库里没有消息 ID 时会改问协议端。
        对用户最终回复只要一句结果。

        Args:
            count(number): 撤回最近几条，默认 1，最大 10
        """
        n = int(count) if count else 1
        # 超过上限时夹住，避免一次把最近十几条全撤掉
        n = min(n, RECALL_RECENT_MAX)
        return await recall_recent(event, self._config, self.store, n)

    @filter.llm_tool(name="group_set_title")
    async def tool_group_set_title(
        self, event: AstrMessageEvent, user_id: str, title: str = ""
    ) -> str:
        """设置或清空某个群成员的专属头衔。空字符串表示清空。
        对用户最终回复只要一句结果。

        Args:
            user_id(string): 要改头衔的群成员 QQ 号，必须是纯数字
            title(string): 新的专属头衔；空字符串表示清空
        """
        return await set_title(event, self._config, user_id, title)

    @filter.llm_tool(name="group_poke")
    async def tool_group_poke(self, event: AstrMessageEvent, user_id: str) -> str:
        """在本群戳一戳某个成员。对用户最终回复只要一句结果。

        Args:
            user_id(string): 要戳的群成员 QQ 号，必须是纯数字
        """
        return await poke_member(event, self._config, user_id)

    @filter.llm_tool(name="group_join_list")
    async def tool_group_join_list(self, event: AstrMessageEvent) -> str:
        """列出本群尚未处理的加群申请。同意或拒绝时要用返回的 flag。

        Args: 无
        """
        return await list_join_requests(event, self._config)

    @filter.llm_tool(name="group_join_handle")
    async def tool_group_join_handle(
        self,
        event: AstrMessageEvent,
        flag: str,
        approve: bool,
        reason: str = "",
    ) -> str:
        """同意或拒绝一条加群申请。flag 来自 group_join_list。
        对用户最终回复只要一句结果。

        Args:
            flag(string): 申请标识，必须来自 group_join_list
            approve(boolean): true 同意，false 拒绝
            reason(string): 拒绝理由，同意时可空
        """
        return await handle_join_request(event, self._config, flag, approve, reason)

    @filter.llm_tool(name="group_set_admin")
    async def tool_group_set_admin(
        self,
        event: AstrMessageEvent,
        user_id: str,
        enable: bool = True,
        group_id: str = "",
    ) -> str:
        """设置或取消群管理员。没填群号时用当前群。

        Args:
            user_id(string): 目标 QQ 号，必须是纯数字
            enable(boolean): true 设为管理员，false 取消
            group_id(string): 可选群号
        """
        return await set_admin(event, self._config, user_id, enable, group_id)

    @filter.llm_tool(name="group_set_name")
    async def tool_group_set_name(
        self, event: AstrMessageEvent, group_name: str, group_id: str = ""
    ) -> str:
        """修改群名称。没填群号时用当前群。

        Args:
            group_name(string): 新群名，不能为空
            group_id(string): 可选群号
        """
        return await set_group_name(event, self._config, group_name, group_id)

    @filter.llm_tool(name="group_essence_list")
    async def tool_group_essence_list(
        self, event: AstrMessageEvent, group_id: str = ""
    ) -> str:
        """获取群精华消息列表，只给后续工具用，不要念给用户。

        Args:
            group_id(string): 可选群号
        """
        return await list_essence(event, self._config, group_id)

    @filter.llm_tool(name="group_essence_set")
    async def tool_group_essence_set(
        self, event: AstrMessageEvent, message_id: str, group_id: str = ""
    ) -> str:
        """把一条消息设为精华。message_id 必须是数字。

        Args:
            message_id(string): 消息 ID
            group_id(string): 可选群号
        """
        return await set_essence(event, self._config, message_id, group_id)

    @filter.llm_tool(name="group_essence_delete")
    async def tool_group_essence_delete(
        self, event: AstrMessageEvent, message_id: str, group_id: str = ""
    ) -> str:
        """把一条消息移出精华。

        Args:
            message_id(string): 消息 ID
            group_id(string): 可选群号
        """
        return await delete_essence(event, self._config, message_id, group_id)

    @filter.llm_tool(name="group_notice_delete")
    async def tool_group_notice_delete(
        self, event: AstrMessageEvent, notice_id: str, group_id: str = ""
    ) -> str:
        """删除一条群公告。notice_id 来自 group_notice_list。

        Args:
            notice_id(string): 公告 ID
            group_id(string): 可选群号
        """
        return await delete_notice(event, self._config, notice_id, group_id)

    @filter.llm_tool(name="group_join_option")
    async def tool_group_join_option(
        self,
        event: AstrMessageEvent,
        add_type: str,
        question: str = "",
        answer: str = "",
        group_id: str = "",
    ) -> str:
        """修改加群方式。

        Args:
            add_type(string): 任何人 / 验证 / 不允许 / 问题，或 1/2/3/4
            question(string): 加群问题，选「问题」时用
            answer(string): 加群答案，选「问题」时用
            group_id(string): 可选群号
        """
        return await set_join_option(
            event, self._config, add_type, question, answer, group_id
        )

    @filter.llm_tool(name="group_invite_policy")
    async def tool_group_invite_policy(
        self, event: AstrMessageEvent, policy: str, group_id: str = ""
    ) -> str:
        """修改成员邀请好友进群的策略。

        Args:
            policy(string): 禁止 / 审核 / 无需审核 / 百人以下无需审核
            group_id(string): 可选群号
        """
        return await set_invite_policy(event, self._config, policy, group_id)

    @filter.llm_tool(name="group_todo")
    async def tool_group_todo(
        self,
        event: AstrMessageEvent,
        action: str,
        message_id: str,
        group_id: str = "",
    ) -> str:
        """设置、完成或取消群待办。message_id 来自聊天记录。

        Args:
            action(string): set / complete / cancel
            message_id(string): 消息 ID
            group_id(string): 可选群号
        """
        return await group_todo(event, self._config, action, message_id, group_id)

    @filter.llm_tool(name="group_sign")
    async def tool_group_sign(self, event: AstrMessageEvent, group_id: str = "") -> str:
        """群打卡。

        Args:
            group_id(string): 可选群号
        """
        return await group_sign(event, self._config, group_id)

    @filter.llm_tool(name="group_signed_list")
    async def tool_group_signed_list(
        self, event: AstrMessageEvent, group_id: str = ""
    ) -> str:
        """查看今日打卡名单。

        Args:
            group_id(string): 可选群号
        """
        return await signed_list(event, self._config, group_id)

    @filter.llm_tool(name="group_honor")
    async def tool_group_honor(
        self, event: AstrMessageEvent, kind: str = "all", group_id: str = ""
    ) -> str:
        """查看群荣誉（龙王等）。对用户不要照念全部榜单。

        Args:
            kind(string): all / talkative / performer / legend / emotion / strong_newbie
            group_id(string): 可选群号
        """
        return await honor_info(event, self._config, kind, group_id)

    @filter.llm_tool(name="group_at_all_remain")
    async def tool_group_at_all_remain(
        self, event: AstrMessageEvent, group_id: str = ""
    ) -> str:
        """查看本群还能 @全体 几次。

        Args:
            group_id(string): 可选群号
        """
        return await at_all_remain(event, self._config, group_id)

    @filter.llm_tool(name="ocr_image")
    async def tool_ocr_image(self, event: AstrMessageEvent, image: str) -> str:
        """识别图片里的文字，只给后续判断用，不要把全文贴群里。仅 Windows NapCat 可用。

        Args:
            image(string): 图片 URL、路径或 file_id
        """
        return await ocr_image(event, self._config, image)

    @filter.llm_tool(name="ptt_text")
    async def tool_ptt_text(self, event: AstrMessageEvent, message_id: str) -> str:
        """把一条语音转成文字，只给后续判断用，不要把全文贴群里。

        Args:
            message_id(string): 语音消息 ID
        """
        return await ptt_text(event, self._config, message_id)

    @filter.llm_tool(name="msg_emoji_like")
    async def tool_msg_emoji_like(
        self,
        event: AstrMessageEvent,
        message_id: str,
        emoji_id: str = "76",
        set_on: bool = True,
    ) -> str:
        """给消息贴表情回复。默认 76（赞）。

        Args:
            message_id(string): 消息 ID
            emoji_id(string): 表情 ID，默认 76
            set_on(boolean): true 贴上，false 取消
        """
        return await emoji_like(event, self._config, message_id, emoji_id, set_on)

    @filter.llm_tool(name="qq_group_list")
    async def tool_qq_group_list(self, event: AstrMessageEvent) -> str:
        """列出机器人所在群。只有 AstrBot 管理员能用。不要把名单念给用户。

        Args: 无
        """
        return await list_groups(event, self._config)

    @filter.llm_tool(name="group_set_remark")
    async def tool_group_set_remark(
        self, event: AstrMessageEvent, remark: str, group_id: str = ""
    ) -> str:
        """设置机器人自己对某个群的备注，不是改群名。只有 AstrBot 管理员能用。

        Args:
            remark(string): 备注；空字符串表示清空
            group_id(string): 群号，私聊时必填
        """
        return await set_group_remark(event, self._config, remark, group_id)

    @filter.llm_tool(name="friend_list")
    async def tool_friend_list(self, event: AstrMessageEvent, keyword: str = "") -> str:
        """列出机器人好友。只有 AstrBot 管理员能用。不要把名单念给用户。

        Args:
            keyword(string): 可选。按昵称、备注或 QQ 号筛选
        """
        return await list_friends(event, self._config, keyword)

    @filter.llm_tool(name="friend_set_remark")
    async def tool_friend_set_remark(
        self, event: AstrMessageEvent, user_id: str, remark: str = ""
    ) -> str:
        """设置好友备注。只有 AstrBot 管理员能用。

        Args:
            user_id(string): 好友 QQ 号
            remark(string): 备注；空字符串表示清空
        """
        return await set_remark(event, self._config, user_id, remark)

    @filter.llm_tool(name="friend_request_handle")
    async def tool_friend_request_handle(
        self,
        event: AstrMessageEvent,
        flag: str,
        approve: bool,
        remark: str = "",
    ) -> str:
        """处理加好友请求。flag 来自上报。只有 AstrBot 管理员能用。

        Args:
            flag(string): 请求标识
            approve(boolean): true 同意，false 拒绝
            remark(string): 同意后的备注，可空
        """
        return await handle_friend_request(event, self._config, flag, approve, remark)

    @filter.llm_tool(name="doubt_friend_list")
    async def tool_doubt_friend_list(self, event: AstrMessageEvent) -> str:
        """列出可疑好友申请。只有 AstrBot 管理员能用。

        Args: 无
        """
        return await list_doubt_friends(event, self._config)

    @filter.llm_tool(name="doubt_friend_handle")
    async def tool_doubt_friend_handle(
        self, event: AstrMessageEvent, flag: str, approve: bool = True
    ) -> str:
        """处理可疑好友申请。只有 AstrBot 管理员能用。

        Args:
            flag(string): 请求标识
            approve(boolean): 是否同意
        """
        return await handle_doubt_friend(event, self._config, flag, approve)

    @filter.llm_tool(name="send_like")
    async def tool_send_like(
        self, event: AstrMessageEvent, user_id: str, times: int = 1
    ) -> str:
        """给某人点赞。只有 AstrBot 管理员能用。

        Args:
            user_id(string): 对方 QQ 号
            times(number): 次数，默认 1，最大 10
        """
        return await send_like(event, self._config, user_id, int(times or 1))

    @filter.llm_tool(name="stranger_info")
    async def tool_stranger_info(self, event: AstrMessageEvent, user_id: str) -> str:
        """查陌生人资料。只有 AstrBot 管理员能用。不要把全部字段念给用户。

        Args:
            user_id(string): QQ 号
        """
        return await stranger_info(event, self._config, user_id)

    @filter.llm_tool(name="qq_recent_contact")
    async def tool_qq_recent_contact(
        self, event: AstrMessageEvent, count: int = 10
    ) -> str:
        """最近会话。只有 AstrBot 管理员能用。不要把列表念给用户。

        Args:
            count(number): 条数，默认 10，最大 30
        """
        return await recent_contact(event, self._config, int(count or 10))

    @filter.command("禁言自己")
    async def cmd_ban_self(self, event: AstrMessageEvent):
        """全员指令：随机禁言自己 1 到 5 分钟。结果直接发给用户。"""
        msg = await ban_self(event, self._config)
        stop = getattr(event, "stop_event", None)
        # 拦住后续 LLM，避免模型再跟一句
        if callable(stop):
            stop()
        yield event.plain_result(msg)

    @filter.command("群管状态")
    async def cmd_status(self, event: AstrMessageEvent):
        """给管理员看的插件状态。这是指令不是 LLM 工具，结果直接发给用户。"""
        lines = await self._status_lines(event)
        yield event.plain_result("【群管插件状态】\n" + "\n".join(lines))

    async def _status_lines(self, event: AstrMessageEvent) -> list[str]:
        """拼状态文本。"""
        group_id = event.get_group_id()
        lines = [
            f"群号：{group_id or '（私聊）'}",
            f"记录功能：{'开' if self._cfg_bool('enable_history', True) else '关'}",
            f"操作权限：{self._config.get('operator_mode', 'group_admin') if self._config else 'group_admin'}",
        ]
        # 私聊没有群号，统计本群条数没有意义
        if not group_id:
            return lines
        try:
            n = await self.store.count(str(group_id))
            lines.append(f"本群已记录：{n} 条")
            # 0 条多半是群消息没到达插件，提醒一下
            if n == 0:
                lines.append(
                    "如果这里是 0，说明机器人还没收到过本群的非唤醒消息，"
                    "请确认群消息是否到达了 AstrBot。"
                )
        except Exception as exc:
            lines.append(f"读取记录统计失败：{exc}")
        return lines

    async def _cleanup_loop(self) -> None:
        """后台定时删过期记录。"""
        while True:
            hours = max(self._cfg_int("cleanup_interval_hours", 6), 1)
            await asyncio.sleep(hours * 3600)
            days = max(self._cfg_int("retention_days", 30), 1)
            expire_before = int(time.time()) - days * 86400
            try:
                deleted = await self.store.cleanup(expire_before)
                # 没删掉东西就不打日志，避免 6 小时刷一次
                if deleted:
                    logger.info("[group_agent] 清理过期记录 %s 条", deleted)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[group_agent] 清理失败：%s", exc)

    async def terminate(self) -> None:
        """插件停用时停掉清理任务。"""
        task = self._cleanup_task
        # 任务没启动或已结束就不用 cancel
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[group_agent] 停止清理任务失败：%s", exc)


def _event_message_id(event: object) -> str:
    """从事件里取出协议端消息 ID。没有就返回空，这条就撤不了。"""
    obj = getattr(event, "message_obj", None)
    # 没有消息对象时没法取 ID
    if obj is None:
        return ""
    raw = getattr(obj, "message_id", None)
    # 字段缺失或空值都当没有
    if raw is None or raw == "":
        return ""
    return str(raw)
