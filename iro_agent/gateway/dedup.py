import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


class EventDeduplicator:
    """网关事件与消息防重去重持久化管理器"""

    def __init__(self, db_path: str = "iro_agent_gateway_events.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化去重表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_events (
                    event_id TEXT PRIMARY KEY,
                    message_id TEXT,
                    processed_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gw_msg_id ON gateway_events(message_id)
                """
            )
            conn.commit()

    def is_duplicate(self, event_id: Optional[str], message_id: Optional[str] = None) -> bool:
        """
        判断事件或消息是否重复。
        若重复返回 True；若为新事件则记录入库并返回 False。
        """
        if not event_id and not message_id:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        primary_key = event_id or f"msg_{message_id}"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM gateway_events WHERE event_id = ?", (primary_key,))
            if cursor.fetchone():
                return True

            if message_id:
                cursor.execute("SELECT 1 FROM gateway_events WHERE message_id = ?", (message_id,))
                if cursor.fetchone():
                    return True

            cursor.execute(
                "INSERT INTO gateway_events (event_id, message_id, processed_at) VALUES (?, ?, ?)",
                (primary_key, message_id or "", now_iso),
            )
            conn.commit()
            return False

    def clear(self) -> None:
        """清空去重库（供自动化测试使用）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM gateway_events")
            conn.commit()
