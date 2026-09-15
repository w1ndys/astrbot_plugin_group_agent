# 数据层：群聊记录的 SQLite 存取。不判断权限，不调协议端。

import asyncio
import sqlite3
from pathlib import Path

from ..entity.record import ChatRecord


class HistoryStore:
    """把一条群消息写进本地库，或按群号/时间读出来。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = asyncio.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_table()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        """打开连接。WAL 让读写不容易互相堵住。"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _create_table(self) -> None:
        """首次启动时建表。已存在就跳过。"""
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    message_id TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_group_ts ON group_history(group_id, ts)")
            conn.commit()
        finally:
            conn.close()

    def _migrate(self) -> None:
        """给老库补列。不能重建表，旧库里有已经积累的聊天记录。"""
        conn = self._connect()
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(group_history)")}
            # 早于撤回功能的库没有 message_id 列，补上并给旧行留空
            if "message_id" not in cols:
                conn.execute(
                    "ALTER TABLE group_history ADD COLUMN message_id TEXT NOT NULL DEFAULT ''"
                )
                conn.commit()
        finally:
            conn.close()

    async def add(
        self,
        ts: int,
        group_id: str,
        user_id: str,
        name: str,
        text: str,
        message_id: str = "",
    ) -> None:
        """写入一条群消息。失败由调用方记日志，这里只负责入库。"""
        async with self._lock:
            await asyncio.to_thread(self._add_sync, ts, group_id, user_id, name, text, message_id)

    def _add_sync(
        self,
        ts: int,
        group_id: str,
        user_id: str,
        name: str,
        text: str,
        message_id: str,
    ) -> None:
        """同步写入，给 to_thread 用。"""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO group_history(ts, group_id, user_id, name, text, message_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, group_id, user_id, name, text, message_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def fetch(self, group_id: str, since_ts: int, limit: int) -> list[ChatRecord]:
        """按时间正序取出本群一段时间的消息，给总结工具用。"""
        async with self._lock:
            return await asyncio.to_thread(self._fetch_sync, group_id, since_ts, limit)

    def _fetch_sync(self, group_id: str, since_ts: int, limit: int) -> list[ChatRecord]:
        """同步查询。limit 防模型上下文被撑爆。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT ts, name, user_id, text, message_id FROM group_history "
                "WHERE group_id = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
                (group_id, since_ts, limit),
            ).fetchall()
        finally:
            conn.close()
        records = []
        for row in rows:
            records.append(
                ChatRecord(int(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4] or ""))
            )
        return records

    async def recent_ids(self, group_id: str, limit: int) -> list[str]:
        """取本群最近的若干条消息 ID，按时间倒序。撤回功能用。"""
        async with self._lock:
            return await asyncio.to_thread(self._recent_ids_sync, group_id, limit)

    def _recent_ids_sync(self, group_id: str, limit: int) -> list[str]:
        """同步查询最近的消息 ID，跳过没有 ID 的老记录。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT message_id FROM group_history "
                "WHERE group_id = ? AND message_id != '' ORDER BY ts DESC LIMIT ?",
                (group_id, limit),
            ).fetchall()
        finally:
            conn.close()
        ids = []
        for row in rows:
            value = str(row[0] or "")
            # 空 ID 撤不了，直接跳过
            if value:
                ids.append(value)
        return ids

    async def count(self, group_id: str) -> int:
        """本群一共记了多少条，给状态指令展示。"""
        async with self._lock:
            return await asyncio.to_thread(self._count_sync, group_id)

    def _count_sync(self, group_id: str) -> int:
        """同步计数。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM group_history WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        finally:
            conn.close()
        # 理论上 COUNT 总会有一行；没有行就当 0
        if row is None:
            return 0
        return int(row[0])

    async def cleanup(self, expire_before: int) -> int:
        """删掉过期记录，返回删除条数。"""
        async with self._lock:
            return await asyncio.to_thread(self._cleanup_sync, expire_before)

    def _cleanup_sync(self, expire_before: int) -> int:
        """同步删除 ts 早于阈值的行。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM group_history WHERE ts < ?",
                (expire_before,),
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()
