import json
import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config


# 故障记忆验证状态常量 (Phase 13 Memory 写入与防污染规则)
STATUS_OBSERVED = "OBSERVED"
STATUS_AGENT_DIAGNOSIS = "AGENT_DIAGNOSIS"
STATUS_HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
STATUS_REGRESSION_VERIFIED = "REGRESSION_VERIFIED"
VERIFIED_STATUSES = {STATUS_HUMAN_CONFIRMED, STATUS_REGRESSION_VERIFIED}


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
                    similar_incident_ids TEXT,
                    timeline_event_ids TEXT,
                    active_version_provider TEXT
                )
            """)

            # 兼容旧版本表结构迁移：检查并补充新字段
            cursor.execute("PRAGMA table_info(incidents)")
            columns = [row[1] for row in cursor.fetchall()]
            if "timeline_event_ids" not in columns:
                cursor.execute("ALTER TABLE incidents ADD COLUMN timeline_event_ids TEXT")
            if "active_version_provider" not in columns:
                cursor.execute("ALTER TABLE incidents ADD COLUMN active_version_provider TEXT")

            conn.commit()
        finally:
            conn.close()

    def record_incident(self, data: Dict[str, Any]) -> str:
        """记录或更新故障事件，严格维护活跃版本源互斥性"""
        incident_id = data.get("incident_id")
        now_iso = datetime.datetime.now().isoformat()
        if not incident_id:
            incident_id = f"INC-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        active_provider = data.get("active_version_provider") or "None"
        git_commits = data.get("related_git_commits", [])
        wrelease_versions = data.get("related_wrelease_versions", [])

        # 互斥原则：根据活动提供者填充版本信息
        if active_provider == "GitReader":
            wrelease_versions = []
        elif active_provider == "WReleaseReader":
            git_commits = []

        impact_scope_val = data.get("impact_scope")
        if isinstance(impact_scope_val, (dict, list)):
            impact_scope_str = json.dumps(impact_scope_val, ensure_ascii=False, default=str)
        else:
            impact_scope_str = str(impact_scope_val or "")

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
                        resolution_summary = coalesce(?, resolution_summary),
                        active_version_provider = coalesce(?, active_version_provider),
                        timeline_event_ids = coalesce(?, timeline_event_ids)
                    WHERE incident_id = ?
                """, (
                    now_iso,
                    data.get("status"),
                    data.get("fault_domain"),
                    data.get("root_cause"),
                    impact_scope_str,
                    data.get("severity"),
                    data.get("confidence"),
                    data.get("resolution_summary"),
                    active_provider,
                    json.dumps(data.get("timeline_event_ids", []), ensure_ascii=False),
                    incident_id,
                ))
            else:
                cursor.execute("""
                    INSERT INTO incidents (
                        incident_id, project, created_at, updated_at, status, symptom,
                        user_question, fault_domain, root_cause, impact_scope, severity,
                        confidence, related_logs, related_files, related_git_commits,
                        related_wrelease_versions, resolution_summary, similar_incident_ids,
                        timeline_event_ids, active_version_provider
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    impact_scope_str,
                    data.get("severity", "P2"),
                    data.get("confidence", "Medium"),
                    json.dumps(data.get("related_logs", []), ensure_ascii=False),
                    json.dumps(data.get("related_files", []), ensure_ascii=False),
                    json.dumps(git_commits, ensure_ascii=False),
                    json.dumps(wrelease_versions, ensure_ascii=False),
                    data.get("resolution_summary", ""),
                    json.dumps(data.get("similar_incident_ids", []), ensure_ascii=False),
                    json.dumps(data.get("timeline_event_ids", []), ensure_ascii=False),
                    active_provider,
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
            for k in [
                "related_logs",
                "related_files",
                "related_git_commits",
                "related_wrelease_versions",
                "similar_incident_ids",
                "timeline_event_ids",
            ]:
                try:
                    res[k] = json.loads(res[k]) if res.get(k) else []
                except Exception:
                    res[k] = []
            return res
        finally:
            conn.close()

    def find_similar_incidents(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """基于故障现象或问题关键字匹配历史事件，经人工/回归验证的案例拥有高置信权重"""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            kw_pattern = f"%{keyword.strip()}%"
            cursor.execute("""
                SELECT * FROM incidents 
                WHERE symptom LIKE ? OR user_question LIKE ? OR root_cause LIKE ? OR fault_domain LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (kw_pattern, kw_pattern, kw_pattern, kw_pattern, limit * 2))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                st = item.get("status", "").upper()
                is_verified = st in VERIFIED_STATUSES
                item["is_verified"] = is_verified
                item["evidence_weight"] = 1.0 if is_verified else 0.25
                results.append(item)

            # 优先已验证案例，其次按时间
            results.sort(key=lambda x: (1 if x["is_verified"] else 0, x.get("created_at", "")), reverse=True)
            return results[:limit]
        finally:
            conn.close()

    def get_verified_incidents(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取已通过 HUMAN_CONFIRMED 或 REGRESSION_VERIFIED 核验的标杆经验案例"""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM incidents
                WHERE UPPER(status) IN ('HUMAN_CONFIRMED', 'REGRESSION_VERIFIED')
                ORDER BY updated_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_similar_incident_stats(self, keyword: str, days: int = 90) -> Dict[str, Any]:
        """统计近 N 天内的相似故障频次与归因分布，数据必须真实来源于存储记录"""
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
