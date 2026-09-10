import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.scanners.base import BaseCodeScannerAdapter, ScannerResult
from iro_agent.knowledge.scanners.sql_parser import LightweightSqlParser
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence
from iro_agent.security.redactor import redact_secrets


class MyBatisScanner(BaseCodeScannerAdapter):
    """MyBatis Mapper 接口与 XML SQL 映射扫描器"""

    # 正则提取 namespace 与各标签
    MAPPER_TAG_PATTERN = re.compile(r"<mapper\s+namespace\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    SQL_TAG_PATTERN = re.compile(
        r"<(select|insert|update|delete)\s+id\s*=\s*['\"]([^'\"]+)['\"]([^>]*)>(.*?)</\1>",
        re.IGNORECASE | re.DOTALL,
    )

    def detect(self) -> bool:
        """探测是否存在 MyBatis XML 文件或含有 Mapper 接口"""
        for root_str, _, files in os.walk(self.project_root):
            for f in files:
                if f.endswith("Mapper.xml") or f.endswith("Dao.xml"):
                    return True
        return False

    def scan(self) -> ScannerResult:
        entities: List[CodeEntityNode] = []
        relationships: List[CodeRelationshipEdge] = []

        xml_files: List[Path] = []
        for root_str, dirs, files in os.walk(self.project_root):
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {".git", "target", "build", ".idea", ".vscode", "logs"}
            ]
            for f in files:
                if f.endswith(".xml"):
                    xml_files.append(Path(root_str) / f)

        for file_path in xml_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                ns_match = self.MAPPER_TAG_PATTERN.search(content)
                if not ns_match:
                    continue  # 不是 MyBatis mapper xml

                content = redact_secrets(content)
                rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
                namespace = ns_match.group(1).strip()
                mapper_short_name = namespace.split(".")[-1]

                # 注册 Mapper 实体
                mapper_node = CodeEntityNode(
                    entity_id=namespace,
                    entity_type="mapper",
                    name=mapper_short_name,
                    qualified_name=namespace,
                    file_path=rel_path,
                    framework="mybatis",
                )
                entities.append(mapper_node)

                # 匹配所有 select, insert, update, delete 标签
                for tag_match in self.SQL_TAG_PATTERN.finditer(content):
                    tag_type = tag_match.group(1).lower()
                    stmt_id = tag_match.group(2).strip()
                    sql_body = tag_match.group(4)

                    full_stmt_id = f"{namespace}.{stmt_id}"
                    start_line = content[:tag_match.start()].count("\n") + 1

                    # 创建 SQL statement 实体
                    sql_node = CodeEntityNode(
                        entity_id=full_stmt_id,
                        entity_type="sql_statement",
                        name=stmt_id,
                        qualified_name=full_stmt_id,
                        file_path=rel_path,
                        start_line=start_line,
                        framework="mybatis",
                        metadata={"tag_type": tag_type},
                    )
                    entities.append(sql_node)

                    # Mapper 包含/调用 该 SQL 语句
                    relationships.append(
                        CodeRelationshipEdge(
                            source_entity_id=namespace,
                            relationship_type="CALLS",
                            target_entity_id=full_stmt_id,
                            confidence="confirmed",
                            evidence=CodeEvidence(
                                file_path=rel_path,
                                start_line=start_line,
                                snippet=f"<{tag_type} id=\"{stmt_id}\">",
                            ),
                        )
                    )

                    # 使用 LightweightSqlParser 分析目标表
                    sql_info = LightweightSqlParser.parse(sql_body)
                    found_cols = sql_info.get("columns", [])

                    for tbl in sql_info.get("read_tables", []):
                        tbl_node_id = f"table:{tbl}"
                        # 补充 table 实体
                        entities.append(
                            CodeEntityNode(
                                entity_id=tbl_node_id,
                                entity_type="table",
                                name=tbl,
                                qualified_name=tbl,
                                metadata={"fields": list(found_cols), "mapped_table": tbl},
                            )
                        )
                        # SQL 语句 READS_TABLE
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=full_stmt_id,
                                relationship_type="READS_TABLE",
                                target_entity_id=tbl_node_id,
                                confidence="confirmed",
                                evidence=CodeEvidence(
                                    file_path=rel_path,
                                    start_line=start_line,
                                    snippet=sql_body.strip()[:100],
                                ),
                            )
                        )
                        # 直接为 Mapper 建立快速边
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=namespace,
                                relationship_type="READS_TABLE",
                                target_entity_id=tbl_node_id,
                                confidence="confirmed",
                            )
                        )

                    for tbl in sql_info.get("write_tables", []):
                        tbl_node_id = f"table:{tbl}"
                        entities.append(
                            CodeEntityNode(
                                entity_id=tbl_node_id,
                                entity_type="table",
                                name=tbl,
                                qualified_name=tbl,
                                metadata={"fields": list(found_cols), "mapped_table": tbl},
                            )
                        )
                        # SQL 语句 WRITES_TABLE
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=full_stmt_id,
                                relationship_type="WRITES_TABLE",
                                target_entity_id=tbl_node_id,
                                confidence="confirmed",
                                evidence=CodeEvidence(
                                    file_path=rel_path,
                                    start_line=start_line,
                                    snippet=sql_body.strip()[:100],
                                ),
                            )
                        )
                        # 直接为 Mapper 建立快速边
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=namespace,
                                relationship_type="WRITES_TABLE",
                                target_entity_id=tbl_node_id,
                                confidence="confirmed",
                            )
                        )

            except Exception:
                continue

        return ScannerResult(entities=entities, relationships=relationships)
