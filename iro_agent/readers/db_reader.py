import re
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config, DatabaseConfig
from iro_agent.security.policy import SecurityPolicyError
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.limits import bounded_int, MAX_RESULTS, MAX_OUTPUT_CHARS


class DatabaseReader:
    """PostgreSQL / MySQL：SQL 检查、只读事务、服务端查询超时与返回行数限制。"""

    FORBIDDEN_SQL_PATTERNS = [
        re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|LOCK)\b", re.IGNORECASE),
        re.compile(r";\s*\S+"),  # 禁止多语句注入
        re.compile(r"\b(INTO|OUTFILE|DUMPFILE|LOAD_FILE|SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK|SET_CONFIG)\b", re.IGNORECASE),
        re.compile(r"/\*[!+]"),  # MySQL executable comments / timeout override hints.
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
        bounded_int(max_rows, "max_rows", MAX_RESULTS)
        if not isinstance(query, str) or len(query) > MAX_OUTPUT_CHARS:
            raise ValueError("SQL 必须为不超过 50000 字符的字符串")
        self._validate_sql_readonly(query)
        if not self.db_cfg.host or not self.db_cfg.database or not self.db_cfg.user:
            raise ValueError("observability_gap: 未配置数据库来源")

        conn = None
        try:
            common = dict(host=self.db_cfg.host, port=self.db_cfg.port, user=self.db_cfg.user,
                          password=self.db_cfg.password, connect_timeout=self.db_cfg.connect_timeout)
            timeout_ms = self.db_cfg.query_timeout * 1000
            if self.db_cfg.type == "mysql":
                import pymysql
                conn = pymysql.connect(**common, database=self.db_cfg.database, charset="utf8mb4",
                                       autocommit=False, local_infile=False,
                                       read_timeout=self.db_cfg.query_timeout,
                                       write_timeout=self.db_cfg.query_timeout,
                                       cursorclass=pymysql.cursors.DictCursor)
                cursor = conn.cursor()
            else:
                import psycopg2
                import psycopg2.extras
                conn = psycopg2.connect(**common, dbname=self.db_cfg.database)
                conn.set_session(readonly=True, autocommit=False)
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            with cursor as cur:
                if self.db_cfg.type == "mysql":
                    cur.execute("SET SESSION max_execution_time = %s", (timeout_ms,))
                    cur.execute("START TRANSACTION READ ONLY")
                else:
                    cur.execute("SET LOCAL statement_timeout = %s", (timeout_ms,))
                statement = query.strip().rstrip(";")
                parameters = tuple(params or ())
                # Bound rows at the server, not only after a buffered driver has fetched them all.
                if not statement.upper().startswith("EXPLAIN"):
                    statement = f"SELECT * FROM (\n{statement}\n) AS iro_read LIMIT %s"
                    parameters += (max_rows,)
                cur.execute(statement, parameters or None)
                rows = cur.fetchmany(max_rows)
                results = []
                for row in rows:
                    item = {}
                    for k, v in dict(row).items():
                        if hasattr(v, "isoformat"):
                            item[k] = v.isoformat()
                        elif hasattr(v, "__str__") and not isinstance(v, (int, float, bool, list, dict, type(None))):
                            item[k] = str(v)[:MAX_OUTPUT_CHARS]
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
            safe_error = str(e)
            if self.db_cfg.password:
                safe_error = safe_error.replace(self.db_cfg.password, "[REDACTED_SECRET]")
            self.audit.record(
                tool_name="DatabaseReader",
                operation="execute_query",
                target=f"db={self.db_cfg.database}",
                result_summary=f"数据库查询异常: {safe_error}",
                status="ERROR",
            )
            raise
        finally:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
                finally:
                    conn.close()

    def test_connection(self) -> bool:
        """测试数据库连接连通性（安全只读探测）"""
        try:
            self.execute_query("SELECT 1 AS alive", max_rows=1)
            return True
        except Exception:
            return False

    def list_tables(self, schema: Optional[str] = None) -> List[str]:
        """只读获取当前数据库用户基表名称列表"""
        schema = schema or (self.db_cfg.database if self.db_cfg.type == "mysql" else "public")
        sql = """
        SELECT table_name AS table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
        rows = self.execute_query(sql, params=(schema,), max_rows=500)
        return [r["table_name"] for r in rows]

    def describe_table(self, table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """只读获取指定表的字段、类型、主键与是否允许为空"""
        schema = schema or (self.db_cfg.database if self.db_cfg.type == "mysql" else "public")
        clean_tbl = table_name.strip().strip("'\"`")
        if self.db_cfg.type == "mysql":
            return self.execute_query("""
                SELECT column_name AS column_name, data_type AS data_type,
                       is_nullable AS is_nullable, column_default AS column_default,
                       (column_key = 'PRI') AS is_primary_key
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, params=(schema, clean_tbl), max_rows=200)
        sql = """
        SELECT 
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN true ELSE false END as is_primary_key
        FROM information_schema.columns c
        LEFT JOIN information_schema.key_column_usage kcu
            ON c.table_schema = kcu.table_schema
            AND c.table_name = kcu.table_name
            AND c.column_name = kcu.column_name
        LEFT JOIN information_schema.table_constraints tc
            ON kcu.table_schema = tc.table_schema
            AND kcu.table_name = tc.table_name
            AND kcu.constraint_name = tc.constraint_name
            AND tc.constraint_type = 'PRIMARY KEY'
        WHERE c.table_schema = %s AND c.table_name = %s
        ORDER BY c.ordinal_position;
        """
        return self.execute_query(sql, params=(schema, clean_tbl), max_rows=200)

    def get_foreign_keys(self, table_name: Optional[str] = None, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """只读获取外键关联定义"""
        schema = schema or (self.db_cfg.database if self.db_cfg.type == "mysql" else "public")
        if self.db_cfg.type == "mysql":
            sql = """
                SELECT table_name AS table_name, column_name AS column_name, referenced_table_name AS foreign_table_name,
                       referenced_column_name AS foreign_column_name
                FROM information_schema.key_column_usage
                WHERE table_schema = %s AND referenced_table_name IS NOT NULL
            """
            params = (schema,)
            if table_name:
                sql += " AND table_name = %s"
                params += (table_name.strip().strip("'\"`"),)
            return self.execute_query(sql, params=params, max_rows=200)
        if table_name:
            clean_tbl = table_name.strip().strip("'\"`")
            sql = """
            SELECT
                kcu.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND kcu.table_name = %s;
            """
            return self.execute_query(sql, params=(schema, clean_tbl), max_rows=100)
        else:
            sql = """
            SELECT
                kcu.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s;
            """
            return self.execute_query(sql, params=(schema,), max_rows=200)

