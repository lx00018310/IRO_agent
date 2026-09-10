import os
import re
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
from pydantic import BaseModel, Field
from iro_agent.security.redactor import redact_secrets
from iro_agent.knowledge.code_graph import CodeRelationshipGraph
from iro_agent.knowledge.scanners.composite import CompositeCodeScanner


class CodeEntity(BaseModel):
    name: str
    file_path: str
    entity_type: str  # model, service, controller, enum, mapper
    mapped_table: Optional[str] = None
    fields_or_constants: List[str] = Field(default_factory=list)
    docstring_or_comment: str = ""


class CodeScanResult(BaseModel):
    entities: List[CodeEntity] = Field(default_factory=list)
    enums: List[Dict[str, Any]] = Field(default_factory=list)
    detected_models_count: int = 0
    scanned_files_count: int = 0
    code_graph: Optional[Dict[str, Any]] = None


class TargetedCodeScanner:
    """针对性业务代码与多语言架构扫描器 (Java/Spring, MyBatis, Vue, Python)"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.composite = CompositeCodeScanner(self.project_root)

    def scan(self, max_files: int = 200) -> CodeScanResult:
        if not self.project_root.exists() or not self.project_root.is_dir():
            return CodeScanResult()

        # 1. 运行多语言复合扫描器
        scanner_res, graph = self.composite.scan()

        compat_entities: List[CodeEntity] = []
        enums_list: List[Dict[str, Any]] = []

        for node in scanner_res.entities:
            # 实体类型映射
            e_type = node.entity_type
            if e_type in ("entity", "table"):
                e_type = "model"
            fields = node.metadata.get("fields", [])

            mapped_tbl = node.metadata.get("mapped_table")
            if not mapped_tbl and node.entity_type == "table":
                mapped_tbl = node.name

            ce = CodeEntity(
                name=node.name,
                file_path=node.file_path,
                entity_type=e_type,
                mapped_table=mapped_tbl,
                fields_or_constants=fields,
            )
            compat_entities.append(ce)

            if node.entity_type == "enum":
                enums_list.append({
                    "name": node.name,
                    "file_path": node.file_path,
                    "fields_or_constants": fields,
                })

        models_count = sum(1 for e in compat_entities if e.entity_type == "model" or e.mapped_table)

        return CodeScanResult(
            entities=compat_entities,
            enums=enums_list,
            detected_models_count=models_count,
            scanned_files_count=len(scanner_res.entities),
            code_graph=graph.to_dict(),
        )
