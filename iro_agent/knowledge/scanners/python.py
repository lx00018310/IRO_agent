import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.scanners.base import BaseCodeScannerAdapter, ScannerResult
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence
from iro_agent.security.redactor import redact_secrets


class PythonScanner(BaseCodeScannerAdapter):
    """Python / Django / SQLAlchemy / FastAPI 结构化静态扫描器"""

    CLASS_DEF_PATTERN = re.compile(r"class\s+([A-Za-z0-9_]+)(?:\([^\)]*\))?:")
    TABLE_NAME_PATTERN = re.compile(r"db_table\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]|__tablename__\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]")
    ENUM_CLASS_PATTERN = re.compile(r"class\s+([A-Za-z0-9_]+)\s*\((?:.*Enum|.*Choices|TextChoices|IntegerChoices)[^\)]*\):")

    def detect(self) -> bool:
        """检查是否存在 Python 代码"""
        for root_str, _, files in os.walk(self.project_root):
            for f in files:
                if f.endswith(".py"):
                    return True
        return False

    def scan(self) -> ScannerResult:
        entities: List[CodeEntityNode] = []
        relationships: List[CodeRelationshipEdge] = []

        candidate_files: List[Path] = []
        for root_str, dirs, files in os.walk(self.project_root):
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {
                    ".git", "node_modules", "dist", "build", "logs",
                    "runtime", "__pycache__", ".venv", "venv", ".idea", ".vscode"
                }
            ]
            for f in files:
                if f.endswith(".py"):
                    candidate_files.append(Path(root_str) / f)

        for file_path in candidate_files:
            rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                content = redact_secrets(content)
                lines = content.splitlines()

                current_entity: Optional[CodeEntityNode] = None

                for idx, line in enumerate(lines, 1):
                    line_strip = line.strip()

                    c_match = self.CLASS_DEF_PATTERN.search(line_strip)
                    if c_match:
                        class_name = c_match.group(1)
                        if class_name.lower() == "meta" and current_entity and current_entity.entity_type == "entity":
                            pass
                        else:
                            is_enum = bool(self.ENUM_CLASS_PATTERN.search(line_strip))
                            ent_type = "enum" if is_enum else "entity"
                            current_entity = CodeEntityNode(
                                entity_id=f"{rel_path}:{class_name}",
                                entity_type=ent_type,
                                name=class_name,
                                qualified_name=f"{rel_path}:{class_name}",
                                file_path=rel_path,
                                start_line=idx,
                                framework="python",
                                metadata={"fields": []},
                            )
                            entities.append(current_entity)

                    if current_entity:
                        t_match = self.TABLE_NAME_PATTERN.search(line_strip)
                        if t_match:
                            tbl = t_match.group(1) or t_match.group(2)
                            current_entity.metadata["mapped_table"] = tbl
                            current_entity.entity_type = "entity"
                            tbl_node_id = f"table:{tbl}"
                            entities.append(
                                CodeEntityNode(
                                    entity_id=tbl_node_id,
                                    entity_type="table",
                                    name=tbl,
                                    qualified_name=tbl,
                                )
                            )
                            relationships.append(
                                CodeRelationshipEdge(
                                    source_entity_id=current_entity.entity_id,
                                    relationship_type="MAPS_TO_TABLE",
                                    target_entity_id=tbl_node_id,
                                    confidence="confirmed",
                                    evidence=CodeEvidence(
                                        file_path=rel_path,
                                        start_line=idx,
                                        snippet=line_strip,
                                    ),
                                )
                            )

                    if current_entity and "=" in line_strip and not line_strip.startswith(("#", "//", "def ", "class ", "return ")):
                        key_part = line_strip.split("=")[0].strip()
                        if re.match(r"^[A-Za-z0-9_]+$", key_part) and key_part not in ("class", "def"):
                            fields = current_entity.metadata.setdefault("fields", [])
                            if len(fields) < 30 and key_part not in fields:
                                fields.append(key_part)

            except Exception:
                continue

        return ScannerResult(entities=entities, relationships=relationships)
