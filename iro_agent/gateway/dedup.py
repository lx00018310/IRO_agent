import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


class EventDeduplicator:
    """网关事件与消息防重去重管理器（基于三态状态机：PROCESSING -> COMPLETED / FAILED）"""

    def __init__(self, db_path: str = "iro_agent_gateway_events.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化去重表，支持状态跟踪与重试锁"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_events (
                    event_id TEXT PRIMARY KEY,
                    message_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_msg TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gw_msg_id ON gateway_events(message_id)
                """
            )
            conn.commit()

    def _get_key(self, event_id: Optional[str], message_id: Optional[str] = None) -> str:
        return event_id or f"msg_{message_id}" or "unknown_event"

    def acquire_lock(self, event_id: Optional[str], message_id: Optional[str] = None, timeout_seconds: int = 120) -> bool:
        """
        尝试抢占事件处理锁。
        - 新事件：置为 PROCESSING 并返回 True（允许处理）；
        - 已 COMPLETED：返回 False（幂等忽略）；
        - 处于 PROCESSING 但已超时（> timeout_seconds）：说明上次崩溃，允许重试并返回 True；
        - 处于 PROCESSING 且未超时：并发防重，返回 False；
        - 处于 FAILED：允许重试，更新为 PROCESSING 并返回 True。
        """
        if not event_id and not message_id:
            return True

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        primary_key = self._get_key(event_id, message_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, updated_at FROM gateway_events WHERE event_id = ?",
                (primary_key,),
            )
            row = cursor.fetchone()

            if not row and message_id:
                cursor.execute(
                    "SELECT status, updated_at FROM gateway_events WHERE message_id = ?",
                    (message_id,),
                )
                row = cursor.fetchone()

            if not row:
                cursor.execute(
                    """
                    INSERT INTO gateway_events (event_id, message_id, status, created_at, updated_at, error_msg)
                    VALUES (?, ?, 'PROCESSING', ?, ?, NULL)
                    """,
                    (primary_key, message_id or "", now_iso, now_iso),
                )
                conn.commit()
                return True

            status, updated_at_str = row[0], row[1]
            if status == "COMPLETED":
                return False

            if status == "PROCESSING":
                try:
                    updated_dt = datetime.fromisoformat(updated_at_str)
                    elapsed = (now_dt - updated_dt).total_seconds()
                    if elapsed > timeout_seconds:
                        # 上一次处理超时，允许重新接管
                        cursor.execute(
                            "UPDATE gateway_events SET status = 'PROCESSING', updated_at = ? WHERE event_id = ?",
                            (now_iso, primary_key),
                        )
                        conn.commit()
                        return True
                    else:
                        # 正在处理中，防止并发重入
                        return False
                except Exception:
                    return False

            if status == "FAILED":
                # 上次处理失败，允许飞书重试接管
                cursor.execute(
                    "UPDATE gateway_events SET status = 'PROCESSING', updated_at = ?, error_msg = NULL WHERE event_id = ?",
                    (now_iso, primary_key),
                )
                conn.commit()
                return True

            return False

    def mark_completed(self, event_id: Optional[str], message_id: Optional[str] = None) -> None:
        """诊断成功且飞书回送成功后标记为 COMPLETED"""
        if not event_id and not message_id:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        primary_key = self._get_key(event_id, message_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE gateway_events SET status = 'COMPLETED', updated_at = ? WHERE event_id = ?",
                (now_iso, primary_key),
            )
            conn.commit()

    def mark_failed(self, event_id: Optional[str], message_id: Optional[str] = None, error: Optional[str] = None) -> None:
        """处理异常时置为 FAILED，释放锁以便重试"""
        if not event_id and not message_id:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        primary_key = self._get_key(event_id, message_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE gateway_events SET status = 'FAILED', updated_at = ?, error_msg = ? WHERE event_id = ?",
                (now_iso, str(error or "")[:500], primary_key),
            )
            conn.commit()

    def is_duplicate(self, event_id: Optional[str], message_id: Optional[str] = None) -> bool:
        """兼容接口：如果无法抢占锁则说明不可处理（即重复）"""
        return not self.acquire_lock(event_id=event_id, message_id=message_id)

    def get_status(self, event_id: Optional[str]) -> Optional[str]:
        """获取指定事件当前状态（供测试与排查）"""
        if not event_id:
            return None
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM gateway_events WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def clear(self) -> None:
        """清空去重库（供自动化测试使用）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM gateway_events")
            conn.commit()
