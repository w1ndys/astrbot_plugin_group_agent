# 新增 QQ 能力：权限摘工具、好友/群列表、加群方式、荣誉、OCR。

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from importlib import import_module

# 包名跟目录名走，避免本地目录还是旧名时导不进
_auth = import_module(ROOT.name + ".business.auth")
_friend = import_module(ROOT.name + ".business.friend")
_extra = import_module(ROOT.name + ".business.group_extra")
_recognize = import_module(ROOT.name + ".business.recognize")
tools_to_hide_before_llm = _auth.tools_to_hide_before_llm
list_friends = _friend.list_friends
send_like = _friend.send_like
honor_info = _extra.honor_info
list_groups = _extra.list_groups
set_group_remark = _extra.set_group_remark
set_join_option = _extra.set_join_option
ocr_image = _recognize.ocr_image


class FakeApi:
    def __init__(self, replies=None, role: str = "admin") -> None:
        self.replies = replies or {}
        self.role = role
        self.calls = []

    async def call_action(self, action: str, **kwargs):
        self.calls.append((action, kwargs))
        if action == "get_group_member_info":
            return {"role": self.role, "user_id": kwargs.get("user_id")}
        if action in self.replies:
            return self.replies[action]
        return {}


class FakeBot:
    def __init__(self, replies=None, role: str = "admin") -> None:
        self.api = FakeApi(replies, role)


class FakeEvent:
    def __init__(
        self,
        group_id: str = "123",
        admin: bool = True,
        replies=None,
        role: str = "admin",
    ) -> None:
        self.group_id = group_id
        self.admin = admin
        self.bot = FakeBot(replies, role)

    def get_group_id(self) -> str:
        return self.group_id

    def get_sender_id(self) -> str:
        return "10086"

    def get_self_id(self) -> str:
        return "999"

    def is_admin(self) -> bool:
        return self.admin


class HideToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_member_hides_all(self) -> None:
        event = FakeEvent(group_id="", admin=False, role="member")
        hidden = await tools_to_hide_before_llm(event, {})
        self.assertIn("group_ban", hidden)
        self.assertIn("group_honor", hidden)
        self.assertIn("friend_list", hidden)
        self.assertIn("group_chat_history", hidden)

    async def test_private_admin_keeps_friend_and_group_id_tools(self) -> None:
        event = FakeEvent(group_id="", admin=True)
        hidden = await tools_to_hide_before_llm(event, {})
        self.assertIn("group_ban", hidden)
        self.assertNotIn("friend_list", hidden)
        self.assertNotIn("group_honor", hidden)
        self.assertNotIn("group_member_list", hidden)

    async def test_group_qq_admin_hides_friend(self) -> None:
        event = FakeEvent(group_id="123", admin=False, role="admin")
        hidden = await tools_to_hide_before_llm(event, {})
        self.assertIn("friend_list", hidden)
        self.assertIn("qq_group_list", hidden)
        self.assertNotIn("group_ban", hidden)
        self.assertNotIn("group_honor", hidden)
        self.assertNotIn("group_set_remark", hidden)


class GroupExtraTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_groups_admin_only(self) -> None:
        event = FakeEvent(admin=False, replies={"get_group_list": []})
        text = await list_groups(event, {})
        self.assertIn("只有 AstrBot 管理员", text)

    async def test_list_groups_format(self) -> None:
        event = FakeEvent(
            replies={
                "get_group_list": [
                    {"group_id": 1, "group_name": "甲", "member_count": 3},
                    {"group_id": 2, "group_name": "乙"},
                ]
            }
        )
        text = await list_groups(event, {})
        self.assertIn("所在群 2 个", text)
        self.assertIn("不要念给用户", text)
        self.assertIn("群 1  甲  人数 3", text)

    async def test_join_option_maps_chinese(self) -> None:
        event = FakeEvent()
        text = await set_join_option(event, {}, "验证")
        self.assertEqual(text, "已修改加群方式（验证）。")
        action, kwargs = event.bot.api.calls[-1]
        self.assertEqual(action, "set_group_add_option")
        self.assertEqual(kwargs["add_type"], 2)

    async def test_group_remark_qq_admin(self) -> None:
        event = FakeEvent(admin=False, role="admin")
        text = await set_group_remark(event, {}, "值班群")
        self.assertEqual(text, "已将群 123 的备注设为「值班群」。")
        action, kwargs = event.bot.api.calls[-1]
        self.assertEqual(action, "set_group_remark")
        self.assertEqual(str(kwargs["group_id"]), "123")

    async def test_group_remark_member_rejected(self) -> None:
        event = FakeEvent(admin=False, role="member")
        text = await set_group_remark(event, {}, "值班群")
        self.assertIn("不能执行群管操作", text)

    async def test_join_option_rejects_unknown(self) -> None:
        event = FakeEvent()
        text = await set_join_option(event, {}, "随便")
        self.assertIn("加群方式只能是", text)
        actions = [a for a, _ in event.bot.api.calls if a == "set_group_add_option"]
        self.assertEqual(actions, [])

    async def test_honor_format(self) -> None:
        event = FakeEvent(
            replies={
                "get_group_honor_info": {
                    "current_talkative": {
                        "user_id": 1,
                        "nickname": "龙",
                        "day_count": 3,
                    },
                    "talkative_list": [
                        {"user_id": 2, "nickname": "甲"},
                    ],
                }
            }
        )
        text = await honor_info(event, {})
        self.assertIn("当前龙王：龙(1) 3", text)
        self.assertIn("龙王榜：甲(2)", text)


class FriendTest(unittest.IsolatedAsyncioTestCase):
    async def test_friend_list_keyword(self) -> None:
        event = FakeEvent(
            replies={
                "get_friend_list": [
                    {"user_id": 1, "nickname": "张三", "remark": ""},
                    {"user_id": 2, "nickname": "李四", "remark": "班长"},
                ]
            }
        )
        text = await list_friends(event, {}, "班长")
        self.assertIn("好友 1 人", text)
        self.assertIn("QQ 2", text)
        self.assertNotIn("QQ 1  ", text)

    async def test_friend_list_rejects_non_admin(self) -> None:
        event = FakeEvent(admin=False)
        text = await list_friends(event, {}, "")
        self.assertIn("只有 AstrBot 管理员", text)

    async def test_like_clamps_times(self) -> None:
        event = FakeEvent()
        text = await send_like(event, {}, "12345", 99)
        self.assertEqual(text, "已给 12345 点赞 10 次。")
        _action, kwargs = event.bot.api.calls[-1]
        self.assertEqual(kwargs["times"], 10)


class OcrTest(unittest.IsolatedAsyncioTestCase):
    async def test_ocr_joins_texts(self) -> None:
        event = FakeEvent(
            replies={"ocr_image": {"texts": [{"text": "你好"}, {"text": "世界"}]}}
        )
        text = await ocr_image(event, {}, "http://x/a.png")
        self.assertIn("不要把全文贴到群里", text)
        self.assertIn("你好", text)
        self.assertIn("世界", text)

    async def test_ocr_empty_image(self) -> None:
        event = FakeEvent()
        text = await ocr_image(event, {}, "  ")
        self.assertIn("image 不能为空", text)
