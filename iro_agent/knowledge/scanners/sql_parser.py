import re
from typing import Dict, Any, List, Set, Tuple


class LightweightSqlParser:
    """轻量级工业 SQL 静态分析器 (纯静态正则与分词提取，绝不连接或执行数据库)"""

    SELECT_COL_PATTERN = re.compile(r"\bSELECT\s+(.+?)\s+\bFROM\b", re.IGNORECASE | re.DOTALL)
    FROM_PATTERN = re.compile(r"\bFROM\s+([a-zA-Z0-9_`\"\. ]+?)(?:\s+WHERE\b|\s+JOIN\b|\s+LEFT\b|\s+RIGHT\b|\s+INNER\b|\s+ORDER\b|\s+GROUP\b|\s+LIMIT\b|;|\)|$)", re.IGNORECASE)
    JOIN_PATTERN = re.compile(r"\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\s+([a-zA-Z0-9_`\"\.]+)", re.IGNORECASE)
    INSERT_PATTERN = re.compile(r"\bINSERT\s+INTO\s+([a-zA-Z0-9_`\"\.]+)(?:\s*\(([^\)]+)\))?", re.IGNORECASE)
    UPDATE_PATTERN = re.compile(r"\bUPDATE\s+([a-zA-Z0-9_`\"\.]+)(?:\s+SET\s+(.+?))?(?:\s+WHERE\b|;|$)", re.IGNORECASE | re.DOTALL)
    DELETE_PATTERN = re.compile(r"\bDELETE\s+FROM\s+([a-zA-Z0-9_`\"\.]+)", re.IGNORECASE)
    WHERE_COL_PATTERN = re.compile(r"\bWHERE\b\s+(.+?)(?:\s+ORDER\b|\s+GROUP\b|\s+LIMIT\b|;|$)", re.IGNORECASE | re.DOTALL)
    ORDER_COL_PATTERN = re.compile(r"\bORDER\s+BY\s+([a-zA-Z0-9_`\",\.\s]+?)(?:\s+ASC|\s+DESC|\s+LIMIT|;|$)", re.IGNORECASE)

    @classmethod
    def clean_table_name(cls, raw: str) -> str:
        """清理表名并去除别名、反引号、双引号与数据库前缀"""
        t = raw.strip().replace("`", "").replace('"', "")
        tokens = t.split()
        if not tokens:
            return ""
        name = tokens[0]
        if "." in name:
            name = name.split(".")[-1]
        return name.strip()

    @classmethod
    def clean_col_name(cls, raw: str) -> str:
        c = raw.strip().replace("`", "").replace('"', "")
        tokens = c.split()
        if not tokens:
            return ""
        name = tokens[0]
        if "." in name:
            name = name.split(".")[-1]
        return name.strip()

    @classmethod
    def parse(cls, sql_text: str) -> Dict[str, Any]:
        """解析单条 SQL 文本并返回结构化分析结果"""
        sql_clean = re.sub(r"--.*$", "", sql_text, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        sql_clean = sql_clean.strip()

        read_tables: Set[str] = set()
        write_tables: Set[str] = set()
        operation_types: Set[str] = set()
        columns_found: List[str] = []

        # 1. 检测 INSERT
        insert_match = cls.INSERT_PATTERN.search(sql_clean)
        if insert_match:
            tbl = cls.clean_table_name(insert_match.group(1))
            if tbl:
                write_tables.add(tbl)
                operation_types.add("INSERT")
            cols_str = insert_match.group(2)
            if cols_str:
                for c in cols_str.split(","):
                    c_clean = cls.clean_col_name(c)
                    if c_clean and c_clean not in columns_found:
                        columns_found.append(c_clean)

        # 2. 检测 UPDATE
        update_match = cls.UPDATE_PATTERN.search(sql_clean)
        if update_match:
            tbl = cls.clean_table_name(update_match.group(1))
            if tbl:
                write_tables.add(tbl)
                operation_types.add("UPDATE")
            set_str = update_match.group(2)
            if set_str:
                for part in set_str.split(","):
                    left = part.split("=")[0]
                    c_clean = cls.clean_col_name(left)
                    if c_clean and c_clean not in columns_found:
                        columns_found.append(c_clean)

        # 3. 检测 DELETE
        delete_match = cls.DELETE_PATTERN.search(sql_clean)
        if delete_match:
            tbl = cls.clean_table_name(delete_match.group(1))
            if tbl:
                write_tables.add(tbl)
                operation_types.add("DELETE")

        # 4. 检测 SELECT 与列名
        sel_match = cls.SELECT_COL_PATTERN.search(sql_clean)
        if sel_match:
            cols_raw = sel_match.group(1)
            for c in cols_raw.split(","):
                c_clean = cls.clean_col_name(c)
                if c_clean and c_clean != "*" and c_clean not in columns_found and not c_clean.startswith("("):
                    columns_found.append(c_clean)

        # 5. 检测 FROM (SELECT)
        from_matches = cls.FROM_PATTERN.findall(sql_clean)
        for fm in from_matches:
            sub_tables = fm.split(",")
            for st in sub_tables:
                tbl = cls.clean_table_name(st)
                if tbl and tbl.lower() not in ("select", "where", "group", "order", "limit"):
                    read_tables.add(tbl)
                    operation_types.add("SELECT")

        # 6. 检测 JOIN
        join_matches = cls.JOIN_PATTERN.findall(sql_clean)
        for jm in join_matches:
            tbl = cls.clean_table_name(jm)
            if tbl:
                read_tables.add(tbl)

        # 7. 检测 WHERE 关键字段
        where_cols: List[str] = []
        where_match = cls.WHERE_COL_PATTERN.search(sql_clean)
        if where_match:
            where_clause = where_match.group(1)
            candidates = re.findall(r"([a-zA-Z0-9_]+)\s*(?:=|!=|<>|>|<|>=|<=|\bIN\b|\bLIKE\b|\bIS\b)", where_clause, re.IGNORECASE)
            for c in candidates:
                if c.upper() not in ("AND", "OR", "NOT", "NULL", "TRUE", "FALSE") and c not in where_cols:
                    where_cols.append(c)
                    if c not in columns_found:
                        columns_found.append(c)

        # 8. 检测 ORDER BY
        order_cols: List[str] = []
        order_match = cls.ORDER_COL_PATTERN.search(sql_clean)
        if order_match:
            order_clause = order_match.group(1)
            for col in order_clause.split(","):
                c_clean = cls.clean_col_name(col)
                if c_clean and c_clean not in order_cols:
                    order_cols.append(c_clean)
                    if c_clean not in columns_found:
                        columns_found.append(c_clean)

        return {
            "operations": list(operation_types),
            "read_tables": list(read_tables),
            "write_tables": list(write_tables),
            "columns": columns_found,
            "where_columns": where_cols,
            "order_columns": order_cols,
        }
