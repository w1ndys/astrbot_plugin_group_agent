# 入口层：向 AstrBot 注册 LLM 工具、群消息记录和状态指令。
# 真正的权限判断和协议调用在 business 里。
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

from .business.history import read_history
from .business.ops import ban_all, ban_member, kick_member, set_card
from .business.parse import clip_text, render_message
from .business.query import query_member
from .business.settings import get_bool, get_int
from .data.store import HistoryStore
from .entity.constants import DEFAULT_BAN_MINUTES


class GroupAgentPlugin(Star):
    """AstrBot 群管插件。把自然语言收成 OneBot 群管动作。"""

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self._config = config
        data_dir = Path(StarTools.get_data_dir())
        db_path = data_dir / "group_history.db"
        self.store = HistoryStore(db_path)
        logger.info("[group_agent] 群聊记录库已就绪：%s", db_path)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def _cfg_int(self, key: str, default: int) -> int:
        """入口里读整数配置的短封装。"""
        return get_int(self._config, key, default)

    def _cfg_bool(self, key: str, default: bool) -> bool:
        """入口里读开关配置的短封装。"""
        return get_bool(self._config, key, default)

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
        try:
            await self.store.add(
                int(time.time()),
                str(group_id),
                str(event.get_sender_id()),
                event.get_sender_name() or "未知用户",
                text,
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
        """禁言或解除禁言某个群成员。

        Args:
            user_id(string): 要操作的群成员 QQ 号，必须是纯数字
            duration_minutes(number): 禁言时长，单位为分钟；填 0 表示解除禁言；最大 43200
            reason(string): 禁言原因，仅用于向群友说明，可以为空
        """
        return await ban_member(event, self._config, user_id, duration_minutes, reason)

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
        """查询群成员。可按 QQ 号查、按昵称反查 QQ 号，或列出管理员。

        Args:
            user_id(string): 要查询的 QQ 号，和 keyword、list_admins 三选一
            keyword(string): 昵称或群名片关键字，用来反查 QQ 号
            list_admins(boolean): true 时列出本群群主和管理员
        """
        return await query_member(event, self._config, user_id, keyword, list_admins)

    @filter.llm_tool(name="group_chat_history")
    async def tool_group_chat_history(
        self,
        event: AstrMessageEvent,
        hours: float = 24,
        max_messages: int = 200,
    ) -> str:
        """获取本群最近一段时间的聊天记录，用于总结。

        Args:
            hours(number): 回溯多少小时，默认 24
            max_messages(number): 最多返回多少条，默认 200
        """
        return await read_history(self.store, event, self._config, hours, int(max_messages))

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
