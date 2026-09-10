from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from iro_agent.config import DatabaseConfig, get_config
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.security.audit import AuditLogger


class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    comment: str = ""


class TableMetadata(BaseModel):
    table_name: str
    table_schema: str = "public"
    columns: List[ColumnMetadata] = Field(default_factory=list)
    primary_key: str = "id"
    foreign_keys: List[Dict[str, str]] = Field(default_factory=list)
    comment: str = ""


class SchemaScanResult(BaseModel):
    database_name: str = ""
    tables: List[TableMetadata] = Field(default_factory=list)
    connected: bool = False
    error: Optional[str] = None


class SchemaScanner:
    """PostgreSQL 数据库元数据只读探测器 (基于 information_schema)"""

    def __init__(self, db_config: Optional[DatabaseConfig] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        self.db_cfg = db_config or self.config.database
        self.audit = audit_logger or AuditLogger()
        self.reader = DatabaseReader(db_config=self.db_cfg, audit_logger=self.audit)

    def scan(self, target_schema: str = "public") -> SchemaScanResult:
        """执行严格只读元数据采集，获取所有用户表、字段、主键与注释"""
        if not self.db_cfg or not self.db_cfg.host or not self.db_cfg.database:
            return SchemaScanResult(connected=False, error="数据库配置为空或未启用")

        try:
            # 1. 探查所有用户基表
            tables_sql = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """
            table_rows = self.reader.execute_query(tables_sql, params=(target_schema,), max_rows=200)
            if not table_rows:
                return SchemaScanResult(database_name=self.db_cfg.database, connected=True, tables=[])

            table_names = [r["table_name"] for r in table_rows]

            # 2. 探查主键
            pk_sql = """
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s;
            """
            pk_rows = self.reader.execute_query(pk_sql, params=(target_schema,), max_rows=500)
            pk_map: Dict[str, str] = {r["table_name"]: r["column_name"] for r in pk_rows}

            # 3. 探查字段列表与类型
            cols_sql = """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position;
            """
            col_rows = self.reader.execute_query(cols_sql, params=(target_schema,), max_rows=2000)

            # 组织为 TableMetadata 列表
            table_cols_map: Dict[str, List[ColumnMetadata]] = {t: [] for t in table_names}
            for c in col_rows:
                t_name = c["table_name"]
                if t_name in table_cols_map:
                    c_name = c["column_name"]
                    is_pk = (pk_map.get(t_name) == c_name)
                    table_cols_map[t_name].append(
                        ColumnMetadata(
                            name=c_name,
                            data_type=c["data_type"],
                            is_nullable=(c["is_nullable"] == "YES"),
                            is_primary_key=is_pk,
                        )
                    )

            tables_res = []
            for t_name in table_names:
                tables_res.append(
                    TableMetadata(
                        table_name=t_name,
                        table_schema=target_schema,
                        columns=table_cols_map.get(t_name, []),
                        primary_key=pk_map.get(t_name, "id"),
                    )
                )

            return SchemaScanResult(
                database_name=self.db_cfg.database,
                tables=tables_res,
                connected=True,
            )

        except Exception as e:
            try:
                err_msg = str(e)
            except Exception:
                err_msg = repr(e)
            return SchemaScanResult(
                database_name=self.db_cfg.database or "",
                connected=False,
                error=err_msg,
            )

