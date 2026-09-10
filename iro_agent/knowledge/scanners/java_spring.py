import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from iro_agent.knowledge.scanners.base import BaseCodeScannerAdapter, ScannerResult
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence
from iro_agent.security.redactor import redact_secrets


class JavaSpringScanner(BaseCodeScannerAdapter):
    """Java / Spring Boot 结构化静态扫描器"""

    PACKAGE_PATTERN = re.compile(r"^\s*package\s+([a-zA-Z0-9_\.]+);", re.MULTILINE)
    CLASS_PATTERN = re.compile(r"(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+)?(class|interface|enum)\s+([a-zA-Z0-9_]+)")
    ANNOTATION_PATTERN = re.compile(r"@([a-zA-Z0-9_]+)(?:\([^\)]*\))?")
    TABLE_ANNOTATION_PATTERN = re.compile(r"@Table\s*\(\s*name\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]", re.IGNORECASE)
    REQUEST_MAPPING_PATTERN = re.compile(r"@(RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping)\s*(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?['\"]([^'\"]+)['\"])?", re.IGNORECASE)
    INJECTED_FIELD_PATTERN = re.compile(r"(?:private|protected|public)?\s+(?:final\s+)?([A-Z][a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s*;")
    METHOD_DEF_PATTERN = re.compile(r"(?:public|protected|private)\s+([a-zA-Z0-9_<>,\s\[\]]+)\s+([a-zA-Z0-9_]+)\s*\(([^\)]*)\)")

    def detect(self) -> bool:
        if (self.project_root / "pom.xml").exists() or (self.project_root / "build.gradle").exists():
            return True
        for root_str, _, files in os.walk(self.project_root):
            for f in files:
                if f.endswith(".java"):
                    return True
        return False

    def scan(self) -> ScannerResult:
        entities: List[CodeEntityNode] = []
        relationships: List[CodeRelationshipEdge] = []

        java_files: List[Path] = []
        for root_str, dirs, files in os.walk(self.project_root):
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {
                    ".git", "target", "build", ".gradle", ".idea", ".vscode", "logs", "bin"
                }
            ]
            for f in files:
                if f.endswith(".java"):
                    java_files.append(Path(root_str) / f)

        for file_path in java_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                content = redact_secrets(content)
                rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
                lines = content.splitlines()

                pkg_match = self.PACKAGE_PATTERN.search(content)
                package_name = pkg_match.group(1) if pkg_match else ""

                current_annotations: List[str] = []
                current_class: Optional[str] = None
                class_role = "generic"
                class_start_line = 1
                class_request_path = ""
                injected_fields: Dict[str, str] = {}  # var_name -> TypeName

                current_method_mapping: Optional[Dict[str, str]] = None

                for idx, line in enumerate(lines, 1):
                    line_strip = line.strip()

                    # 收集注解
                    if line_strip.startswith("@"):
                        ann_matches = self.ANNOTATION_PATTERN.findall(line_strip)
                        for ann in ann_matches:
                            current_annotations.append(ann)

                        rm_match = self.REQUEST_MAPPING_PATTERN.search(line_strip)
                        if rm_match:
                            http_verb = rm_match.group(1).replace("Mapping", "").upper()
                            if http_verb == "REQUEST" or not http_verb:
                                http_verb = "GET"
                            sub_p = rm_match.group(2) or ""
                            if not current_class:
                                class_request_path = sub_p
                            else:
                                current_method_mapping = {"method": http_verb, "path": sub_p}

                    # 类声明匹配
                    c_match = self.CLASS_PATTERN.search(line_strip)
                    if c_match and not current_class and not line_strip.startswith("//"):
                        class_type = c_match.group(1)
                        current_class = c_match.group(2)
                        class_start_line = idx

                        if "RestController" in current_annotations or "Controller" in current_annotations:
                            class_role = "controller"
                        elif "Service" in current_annotations:
                            class_role = "service"
                        elif "Repository" in current_annotations or "Mapper" in current_annotations:
                            class_role = "repository" if "Repository" in current_annotations else "mapper"
                        elif "Entity" in current_annotations or class_type == "class" and any(k in current_class.lower() for k in ("entity", "po", "model")):
                            class_role = "entity"
                        elif class_type == "enum":
                            class_role = "enum"

                        q_name = f"{package_name}.{current_class}" if package_name else current_class
                        cls_node = CodeEntityNode(
                            entity_id=q_name,
                            entity_type=class_role,
                            name=current_class,
                            qualified_name=q_name,
                            file_path=rel_path,
                            start_line=class_start_line,
                            framework="spring",
                            annotations=list(current_annotations),
                        )
                        entities.append(cls_node)

                        if class_role == "entity":
                            tbl_match = self.TABLE_ANNOTATION_PATTERN.search(content)
                            if tbl_match:
                                tbl_name = tbl_match.group(1)
                                cls_node.metadata["mapped_table"] = tbl_name
                                tbl_node_id = f"table:{tbl_name}"
                                entities.append(
                                    CodeEntityNode(
                                        entity_id=tbl_node_id,
                                        entity_type="table",
                                        name=tbl_name,
                                        qualified_name=tbl_name,
                                    )
                                )
                                relationships.append(
                                    CodeRelationshipEdge(
                                        source_entity_id=q_name,
                                        relationship_type="MAPS_TO_TABLE",
                                        target_entity_id=tbl_node_id,
                                        confidence="confirmed",
                                        evidence=CodeEvidence(
                                            file_path=rel_path,
                                            start_line=class_start_line,
                                            snippet=tbl_match.group(0),
                                        ),
                                    )
                                )
                        current_annotations = []
                        continue

                    # 收集依赖注入字段
                    if current_class and ("Autowired" in current_annotations or "Resource" in current_annotations or not line_strip.startswith("@")):
                        f_match = self.INJECTED_FIELD_PATTERN.search(line_strip)
                        if f_match and not line_strip.startswith("//"):
                            f_type = f_match.group(1)
                            f_var = f_match.group(2)
                            if any(k in f_type for k in ("Service", "Mapper", "Repository", "Dao", "Client")):
                                injected_fields[f_var] = f_type
                        if not line_strip.startswith("@"):
                            current_annotations = []

                    # 方法声明匹配
                    if current_class and ("(" in line_strip and ")" in line_strip) and not line_strip.startswith(("//", "/*", "*")):
                        m_match = self.METHOD_DEF_PATTERN.search(line_strip)
                        if m_match:
                            m_name = m_match.group(2)
                            # 仅过滤 Object 原生方法
                            if m_name not in ("equals", "hashCode", "toString", "getClass", "clone", "notify", "wait"):
                                class_id = f"{package_name}.{current_class}" if package_name else current_class
                                method_id = f"{class_id}.{m_name}"

                                # 创建方法实体
                                method_node = CodeEntityNode(
                                    entity_id=method_id,
                                    entity_type="service" if class_role == "service" else ("controller" if class_role == "controller" else "method"),
                                    name=m_name,
                                    qualified_name=method_id,
                                    file_path=rel_path,
                                    start_line=idx,
                                    framework="spring",
                                )
                                entities.append(method_node)

                                # 类包含该方法
                                relationships.append(
                                    CodeRelationshipEdge(
                                        source_entity_id=class_id,
                                        relationship_type="USES",
                                        target_entity_id=method_id,
                                    )
                                )

                                # 如果存在路由注解或处于 Controller 中
                                if current_method_mapping or class_role == "controller":
                                    m_verb = current_method_mapping["method"] if current_method_mapping else "GET"
                                    sub_p = current_method_mapping["path"] if current_method_mapping else f"/{m_name}"
                                    full_p = f"/{class_request_path.strip('/')}/{sub_p.strip('/')}".replace("//", "/").rstrip("/")
                                    if not full_p:
                                        full_p = "/"

                                    api_node = CodeEntityNode(
                                        entity_id=f"api:{m_verb}:{full_p}",
                                        entity_type="api",
                                        name=f"{m_verb} {full_p}",
                                        qualified_name=f"{m_verb} {full_p}",
                                        file_path=rel_path,
                                        start_line=idx,
                                        framework="spring",
                                        metadata={"method": m_verb, "path": full_p, "controller_method": method_id},
                                    )
                                    entities.append(api_node)

                                    # Controller EXPOSES_API API
                                    relationships.append(
                                        CodeRelationshipEdge(
                                            source_entity_id=class_id,
                                            relationship_type="EXPOSES_API",
                                            target_entity_id=api_node.entity_id,
                                            confidence="confirmed",
                                            evidence=CodeEvidence(
                                                file_path=rel_path,
                                                start_line=idx,
                                                snippet=line_strip,
                                            ),
                                        )
                                    )
                                    # Controller Method EXPOSES_API API
                                    relationships.append(
                                        CodeRelationshipEdge(
                                            source_entity_id=method_id,
                                            relationship_type="EXPOSES_API",
                                            target_entity_id=api_node.entity_id,
                                            confidence="confirmed",
                                        )
                                    )

                                current_method_mapping = None

                # 全文扫描注入字段方法调用
                for var_name, type_name in injected_fields.items():
                    call_pattern = re.compile(rf"\b{re.escape(var_name)}\.([a-zA-Z0-9_]+)\s*\(")
                    for match in call_pattern.finditer(content):
                        called_method = match.group(1)
                        src_id = f"{package_name}.{current_class}" if package_name else current_class
                        target_id = type_name
                        rel_type = "CALLS"
                        if "Mapper" in type_name or "Dao" in type_name:
                            rel_type = "CALLS_MAPPER"
                        elif "Service" in type_name:
                            rel_type = "CALLS_SERVICE"
                        elif "Repository" in type_name:
                            rel_type = "CALLS_REPOSITORY"

                        # 为类和具体方法建立下游调用边
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=src_id,
                                relationship_type=rel_type,
                                target_entity_id=target_id,
                                confidence="strongly_inferred",
                                evidence=CodeEvidence(
                                    file_path=rel_path,
                                    start_line=content[:match.start()].count("\n") + 1,
                                    snippet=match.group(0),
                                ),
                                metadata={"target_method": called_method},
                            )
                        )
                        # 也为同名的特定 method 实体加上边
                        for ent in entities:
                            if ent.entity_id.startswith(src_id) and ent.entity_type in ("controller", "service"):
                                relationships.append(
                                    CodeRelationshipEdge(
                                        source_entity_id=ent.entity_id,
                                        relationship_type=rel_type,
                                        target_entity_id=target_id,
                                        confidence="strongly_inferred",
                                    )
                                )

            except Exception:
                continue

        return ScannerResult(entities=entities, relationships=relationships)
