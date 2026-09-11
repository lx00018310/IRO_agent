import sqlite3
import datetime
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config


class LearningMemoryStore:
    """持久化学习记忆库：使用本地 SQLite 存储操作员修正、运维原则与认知规则，支持跨重启持久化检索与防遗忘"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(get_config().storage.memory_db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS learning_rules (
                    rule_id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    topic TEXT,
                    rule_text TEXT NOT NULL,
                    reason TEXT,
                    source_type TEXT NOT NULL,
                    source_message_id TEXT,
                    confidence TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active'
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_rules_project ON learning_rules(project)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_rules_status ON learning_rules(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_rules_topic ON learning_rules(topic)")
            conn.commit()
        finally:
            conn.close()

    def save_rule(self, rule_data: Dict[str, Any]) -> str:
        """持久化保存或更新学习规则，保证数据落盘后返回 rule_id"""
        now_iso = datetime.datetime.now().isoformat()
        rule_id = rule_data.get("rule_id")
        if not rule_id:
            rule_id = f"RULE-{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"

        project = rule_data.get("project") or get_config().project_name or "DEFAULT"
        rule_type = rule_data.get("rule_type") or "operation_rule"
        topic = rule_data.get("topic") or "general"
        rule_text = (rule_data.get("rule_text") or "").strip()
        if not rule_text:
            raise ValueError("rule_text 不能为空")

        reason = rule_data.get("reason") or ""
        source_type = rule_data.get("source_type") or "user_correction"
        source_message_id = rule_data.get("source_message_id") or ""
        confidence = rule_data.get("confidence") or "confirmed"
        status = rule_data.get("status") or "active"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT rule_id FROM learning_rules WHERE rule_id = ?", (rule_id,))
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute("""
                    UPDATE learning_rules SET
                        project = ?,
                        rule_type = ?,
                        topic = ?,
                        rule_text = ?,
                        reason = ?,
                        source_type = ?,
                        source_message_id = ?,
                        confidence = ?,
                        updated_at = ?,
                        status = ?
                    WHERE rule_id = ?
                """, (
                    project, rule_type, topic, rule_text, reason,
                    source_type, source_message_id, confidence, now_iso, status, rule_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO learning_rules (
                        rule_id, project, rule_type, topic, rule_text, reason,
                        source_type, source_message_id, confidence, created_at,
                        updated_at, last_used_at, use_count, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
                """, (
                    rule_id, project, rule_type, topic, rule_text, reason,
                    source_type, source_message_id, confidence, now_iso, now_iso, status
                ))
            conn.commit()
            return rule_id
        finally:
            conn.close()

    def recall_rules(self, query: str, project: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """依据自然语言查询召回相关的已学习规则，按匹配相关度降序排序"""
        q = (query or "").strip().lower()
        if not q:
            return []

        tokens = [t for t in re.split(r"[\s,，、_；;?!？！。]+", q) if len(t) >= 1]
        bigrams = set()
        if len(q) >= 2:
            for i in range(len(q) - 1):
                bg = q[i:i+2].strip()
                if len(bg) == 2:
                    bigrams.add(bg)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if project:
                cursor.execute(
                    "SELECT * FROM learning_rules WHERE status = 'active' AND (project = ? OR project = 'DEFAULT' OR project = '')",
                    (project,)
                )
            else:
                cursor.execute("SELECT * FROM learning_rules WHERE status = 'active'")

            rows = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        scored_rules = []
        for r in rows:
            score = 0
            text_lower = (r["rule_text"] or "").lower()
            topic_lower = (r["topic"] or "").lower()
            reason_lower = (r["reason"] or "").lower()
            rule_type_lower = (r["rule_type"] or "").lower()

            # 1. 完整短语或主题命中
            if topic_lower and topic_lower in q:
                score += 50
            if any(tok in topic_lower for tok in tokens if len(tok) >= 2):
                score += 30

            # 2. 规则文本词与 2-gram 匹配
            for tok in tokens:
                if len(tok) >= 2 and tok in text_lower:
                    score += 20
                elif len(tok) >= 2 and tok in reason_lower:
                    score += 10

            matched_bigrams = [bg for bg in bigrams if bg in text_lower or bg in reason_lower or bg in topic_lower]
            score += len(matched_bigrams) * 5

            # 3. 意图关键词加权（如配置、接口、数据库、表等）
            for kw in ["配置", "config", "表", "table", "接口", "api", "状态", "grep", "目录"]:
                if kw in q and (kw in text_lower or kw in topic_lower or kw in rule_type_lower):
                    score += 15

            if score > 0:
                # 记录得分，若已确认规则加权
                if r["confidence"] == "confirmed":
                    score += 10
                scored_rules.append((score, r))

        scored_rules.sort(key=lambda x: (x[0], x[1]["use_count"]), reverse=True)
        top_rules = []
        for item in scored_rules[:limit]:
            r_dict = dict(item[1])
            # Phase 14 防污染元数据: 历史经验 ≠ 当前事实，仅可用于设置先验优先级，不可充当直接根因证据
            r_dict["source"] = r_dict.get("source_type") or "learning_memory"
            r_dict["confidence"] = r_dict.get("confidence") or "STRONGLY_SUPPORTED"
            r_dict["verified_at"] = r_dict.get("updated_at") or r_dict.get("created_at")
            r_dict["verification_type"] = r_dict.get("source_type") or "user_correction"
            r_dict["is_current_fact"] = False
            r_dict["guidance_role"] = "prior_bias_only"
            top_rules.append(r_dict)

        # 标记本次使用计数
        if top_rules:
            self.mark_used([r["rule_id"] for r in top_rules])

        return top_rules

    def list_rules(
        self,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        status: str = "active"
    ) -> List[Dict[str, Any]]:
        """查询已登记的学习规则列表"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            if topic:
                conditions.append("topic = ?")
                params.append(topic)
            if project:
                conditions.append("(project = ? OR project = 'DEFAULT' OR project = '')")
                params.append(project)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"SELECT * FROM learning_rules {where_clause} ORDER BY created_at DESC", params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def deactivate_rule(self, rule_id: str) -> bool:
        """停用指定规则"""
        now_iso = datetime.datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE learning_rules SET status = 'inactive', updated_at = ? WHERE rule_id = ?",
                (now_iso, rule_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_used(self, rule_ids: List[str]) -> None:
        """更新被召回命中规则的使用次数与最新使用时间戳"""
        if not rule_ids:
            return
        now_iso = datetime.datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in rule_ids)
            cursor.execute(f"""
                UPDATE learning_rules
                SET use_count = use_count + 1, last_used_at = ?
                WHERE rule_id IN ({placeholders})
            """, [now_iso] + rule_ids)
            conn.commit()
        finally:
            conn.close()
