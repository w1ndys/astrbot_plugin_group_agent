# 指定群成员列表：管理员可查当前群或填群号。

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = str(ROOT.parent)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astrbot_plugin_group_agent.business.query import list_members


class FakeApi:
    def __init__(self, members=None, role: str = "member") -> None:
        self.members = members or []
        self.role = role
        self.calls = []

    async def call_action(self, action: str, **kwargs):
        self.calls.append((action, kwargs))
        # 权限检查会先查调用者身份
        if action == "get_group_member_info":
            return {"role": self.role, "user_id": kwargs.get("user_id")}
        if action == "get_group_member_list":
            return self.members
        return {}


class FakeBot:
    def __init__(self, members=None, role: str = "member") -> None:
        self.api = FakeApi(members, role)


class FakeEvent:
    def __init__(
        self,
        group_id: str = "123",
        admin: bool = True,
        members=None,
        role: str = "member",
    ) -> None:
        self.group_id = group_id
        self.admin = admin
        self.bot = FakeBot(members, role)

    def get_group_id(self) -> str:
        return self.group_id

    def get_sender_id(self) -> str:
        return "10086"

    def is_admin(self) -> bool:
        return self.admin


class ListMembersTest(unittest.IsolatedAsyncioTestCase):
    async def test_current_group(self) -> None:
        members = [
            {"user_id": 1, "nickname": "甲", "card": "管理", "role": "admin"},
            {"user_id": 2, "nickname": "乙", "card": "", "role": "member"},
        ]
        event = FakeEvent(members=members)
        text = await list_members(event, {}, "")
        self.assertIn("群 123 成员 2 人", text)
        self.assertIn("不要念给用户", text)
        self.assertIn("QQ 1", text)
        self.assertIn("名片 管理", text)
        action, kwargs = event.bot.api.calls[-1]
        self.assertEqual(action, "get_group_member_list")
        self.assertEqual(kwargs["group_id"], 123)

    async def test_specified_group(self) -> None:
        event = FakeEvent(
            group_id="123",
            members=[{"user_id": 9, "nickname": "丙", "role": "member"}],
        )
        text = await list_members(event, {}, "456")
        self.assertIn("群 456 成员 1 人", text)
        action, kwargs = event.bot.api.calls[-1]
        self.assertEqual(kwargs["group_id"], 456)

    async def test_private_needs_group_id(self) -> None:
        event = FakeEvent(group_id="")
        text = await list_members(event, {}, "")
        self.assertEqual(text, "请指定群号，或在群里使用。")

    async def test_private_with_group_id(self) -> None:
        event = FakeEvent(
            group_id="",
            members=[{"user_id": 8, "nickname": "丁", "role": "member"}],
        )
        text = await list_members(event, {}, "789")
        self.assertIn("群 789 成员 1 人", text)

    async def test_non_admin_rejected(self) -> None:
        event = FakeEvent(admin=False, role="member")
        text = await list_members(event, {}, "")
        self.assertIn("不能执行群管操作", text)

    async def test_empty_list(self) -> None:
        event = FakeEvent(members=[])
        text = await list_members(event, {}, "")
        self.assertEqual(text, "群 123 没有查到成员。")

    async def test_truncates(self) -> None:
        members = [
            {"user_id": i, "nickname": str(i), "role": "member"} for i in range(5)
        ]
        event = FakeEvent(members=members)
        text = await list_members(event, {}, "", limit=2)
        self.assertIn("成员 5 人", text)
        self.assertIn("只返回前 2 人", text)
        self.assertIn("QQ 0", text)
        self.assertNotIn("QQ 4", text)
