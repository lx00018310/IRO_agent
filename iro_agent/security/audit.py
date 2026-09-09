import datetime
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from iro_agent.config import get_config
from iro_agent.security.redactor import redact_secrets


class AuditLogger:
    """内部只读诊断工具审计日志管理器 (写入私有 SQLite，保证操作可追溯)"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(get_config().storage.audit_db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    tool_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    target TEXT,
                    result_summary TEXT,
                    status TEXT NOT NULL,
                    details TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        tool_name: str,
        operation: str,
        target: str = "",
        result_summary: str = "",
        status: str = "SUCCESS",
        session_id: str = "default",
        user_id: str = "system",
        details: Optional[str] = None,
    ) -> int:
        """写入一条审计记录，自动对 target 与 details 进行脱敏"""
        now_iso = datetime.datetime.now().isoformat()
        clean_target = redact_secrets(target)
        clean_summary = redact_secrets(result_summary)
        clean_details = redact_secrets(details) if details else None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_logs 
                (timestamp, session_id, user_id, tool_name, operation, target, result_summary, status, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    session_id,
                    user_id,
                    tool_name,
                    operation,
                    clean_target,
                    clean_summary,
                    status,
                    clean_details,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def query_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的审计记录"""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
