import re
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config, DatabaseConfig
from iro_agent.security.policy import SecurityPolicyError
from iro_agent.security.audit import AuditLogger


class DatabaseReader:
    """PostgreSQL 只读客户端：双重防御（应用层 SQL 白名单过滤 + 数据库只读事务隔离）"""

    FORBIDDEN_SQL_PATTERNS = [
        re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|LOCK)\b", re.IGNORECASE),
        re.compile(r";\s*\S+"),  # 禁止多语句注入
    ]

    ALLOWED_START_PATTERNS = [
        re.compile(r"^\s*SELECT\b", re.IGNORECASE),
        re.compile(r"^\s*WITH\b[\s\S]+\bSELECT\b", re.IGNORECASE),
        re.compile(r"^\s*EXPLAIN\b[\s\S]+\bSELECT\b", re.IGNORECASE),
    ]

    def __init__(self, db_config: Optional[DatabaseConfig] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        self.db_cfg = db_config or self.config.database
        self.audit = audit_logger or AuditLogger()

    def _validate_sql_readonly(self, query: str) -> None:
        """应用层硬校验：必须为 SELECT / WITH / EXPLAIN 且不得包含任何写关键字"""
        trimmed = query.strip()
        if not trimmed:
            raise SecurityPolicyError("SQL 查询语句为空")

        # 校验起始词白名单
        if not any(pattern.match(trimmed) for pattern in self.ALLOWED_START_PATTERNS):
            raise SecurityPolicyError(f"安全策略拦截：仅允许执行只读 SELECT 查询，当前语句起始不符合规范: '{trimmed[:40]}...'")

        # 校验禁止关键字
        for fpattern in self.FORBIDDEN_SQL_PATTERNS:
            if fpattern.search(trimmed):
                raise SecurityPolicyError(f"安全策略拦截：SQL 语句包含禁止修改或多语句注入特征: '{trimmed[:50]}...'")

    def execute_query(self, query: str, params: Optional[tuple] = None, max_rows: int = 100) -> List[Dict[str, Any]]:
        """执行只读查询，返回行记录字典列表"""
        self._validate_sql_readonly(query)

        # 尝试动态导入 psycopg2
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise RuntimeError("psycopg2 未安装，无法连接 PostgreSQL 数据库")

        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_cfg.host,
                port=self.db_cfg.port,
                user=self.db_cfg.user,
                password=self.db_cfg.password,
                dbname=self.db_cfg.database,
                connect_timeout=self.db_cfg.connect_timeout,
            )
            # 开启数据库连接级严格只读
            conn.set_session(readonly=True, autocommit=False)

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchmany(max_rows)
                results = []
                for row in rows:
                    item = {}
                    for k, v in dict(row).items():
                        if hasattr(v, "isoformat"):
                            item[k] = v.isoformat()
                        elif hasattr(v, "__str__") and not isinstance(v, (int, float, bool, list, dict, type(None))):
                            item[k] = str(v)
                        else:
                            item[k] = v
                    results.append(item)

            self.audit.record(
                tool_name="DatabaseReader",
                operation="execute_query",
                target=f"db={self.db_cfg.database} table/query={query[:80]}",
                result_summary=f"查询成功，返回 {len(results)} 行",
                status="SUCCESS",
            )
            return results
        except Exception as e:
            self.audit.record(
                tool_name="DatabaseReader",
                operation="execute_query",
                target=f"db={self.db_cfg.database}",
                result_summary=f"数据库查询异常: {e}",
                status="ERROR",
            )
            raise
        finally:
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass

    def test_connection(self) -> bool:
        """测试数据库连接连通性（安全只读探测）"""
        try:
            self.execute_query("SELECT 1 AS alive", max_rows=1)
            return True
        except Exception:
            return False
