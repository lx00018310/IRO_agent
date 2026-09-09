import json
import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config


class IncidentStore:
    """内部故障记忆库：使用本地 SQLite 持久化历史故障与诊断结论，提供相似案例溯源与统计"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(get_config().storage.memory_db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    user_question TEXT,
                    fault_domain TEXT,
                    root_cause TEXT,
                    impact_scope TEXT,
                    severity TEXT,
                    confidence TEXT,
                    related_logs TEXT,
                    related_files TEXT,
                    related_git_commits TEXT,
                    related_wrelease_versions TEXT,
                    resolution_summary TEXT,
                    similar_incident_ids TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def record_incident(self, data: Dict[str, Any]) -> str:
        """记录或更新故障事件"""
        incident_id = data.get("incident_id")
        now_iso = datetime.datetime.now().isoformat()
        if not incident_id:
            incident_id = f"INC-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT incident_id FROM incidents WHERE incident_id = ?", (incident_id,))
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute("""
                    UPDATE incidents SET
                        updated_at = ?,
                        status = coalesce(?, status),
                        fault_domain = coalesce(?, fault_domain),
                        root_cause = coalesce(?, root_cause),
                        impact_scope = coalesce(?, impact_scope),
                        severity = coalesce(?, severity),
                        confidence = coalesce(?, confidence),
                        resolution_summary = coalesce(?, resolution_summary)
                    WHERE incident_id = ?
                """, (
                    now_iso,
                    data.get("status"),
                    data.get("fault_domain"),
                    data.get("root_cause"),
                    data.get("impact_scope"),
                    data.get("severity"),
                    data.get("confidence"),
                    data.get("resolution_summary"),
                    incident_id,
                ))
            else:
                cursor.execute("""
                    INSERT INTO incidents (
                        incident_id, project, created_at, updated_at, status, symptom,
                        user_question, fault_domain, root_cause, impact_scope, severity,
                        confidence, related_logs, related_files, related_git_commits,
                        related_wrelease_versions, resolution_summary, similar_incident_ids
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident_id,
                    data.get("project", get_config().project_name),
                    now_iso,
                    now_iso,
                    data.get("status", "investigating"),
                    data.get("symptom", ""),
                    data.get("user_question", ""),
                    data.get("fault_domain", "Unknown"),
                    data.get("root_cause", ""),
                    data.get("impact_scope", ""),
                    data.get("severity", "P2"),
                    data.get("confidence", "Medium"),
                    json.dumps(data.get("related_logs", []), ensure_ascii=False),
                    json.dumps(data.get("related_files", []), ensure_ascii=False),
                    json.dumps(data.get("related_git_commits", []), ensure_ascii=False),
                    json.dumps(data.get("related_wrelease_versions", []), ensure_ascii=False),
                    data.get("resolution_summary", ""),
                    json.dumps(data.get("similar_incident_ids", []), ensure_ascii=False),
                ))
            conn.commit()
            return incident_id
        finally:
            conn.close()

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            for k in ["related_logs", "related_files", "related_git_commits", "related_wrelease_versions", "similar_incident_ids"]:
                try:
                    res[k] = json.loads(res[k])
                except Exception:
                    res[k] = []
            return res
        finally:
            conn.close()

    def find_similar_incidents(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """基于故障现象或问题关键字匹配历史事件"""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            kw_pattern = f"%{keyword.strip()}%"
            cursor.execute("""
                SELECT * FROM incidents 
                WHERE symptom LIKE ? OR user_question LIKE ? OR root_cause LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (kw_pattern, kw_pattern, kw_pattern, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_similar_incident_stats(self, keyword: str, days: int = 90) -> Dict[str, Any]:
        """统计近 N 天内的相似故障频次与归因分布"""
        matches = self.find_similar_incidents(keyword, limit=50)

        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        recent_matches = [m for m in matches if m["created_at"] >= cutoff]

        domain_counts: Dict[str, int] = {}
        for m in recent_matches:
            dom = m.get("fault_domain") or "Unknown"
            domain_counts[dom] = domain_counts.get(dom, 0) + 1

        latest_date = recent_matches[0]["created_at"][:10] if recent_matches else "无历史记录"

        return {
            "query_keyword": keyword,
            "period_days": days,
            "total_similar_count": len(recent_matches),
            "domain_breakdown": domain_counts,
            "latest_incident_date": latest_date,
            "recent_incidents": recent_matches[:3],
        }
