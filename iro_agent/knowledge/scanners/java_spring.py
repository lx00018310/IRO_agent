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

    IMPORT_PATTERN = re.compile(r"^\s*import\s+([a-zA-Z0-9_\.]+);", re.MULTILINE)
    MAPPER_XML_PATTERN = re.compile(r"<mapper\s+namespace\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)

    def detect(self) -> bool:
        if (self.project_root / "pom.xml").exists() or (self.project_root / "build.gradle").exists():
            return True
        for root_str, _, files in os.walk(self.project_root):
            for f in files:
                if f.endswith(".java"):
                    return True
        return False

    @staticmethod
    def _compute_method_end_line(lines: List[str], start_idx: int) -> int:
        """根据花括号闭合深度精确计算 Java 方法的作用范围结束行 (1-indexed)"""
        brace_level = 0
        started = False
        for i in range(start_idx - 1, len(lines)):
            line = lines[i]
            comment_idx = line.find("//")
            if comment_idx != -1:
                line = line[:comment_idx]
            for ch in line:
                if ch == '{':
                    brace_level += 1
                    started = True
                elif ch == '}':
                    brace_level -= 1
                    if started and brace_level <= 0:
                        return i + 1
                elif ch == ';' and not started:
                    return i + 1
        return len(lines)

    def _build_global_symbol_table(self, java_files: List[Path]) -> Dict[str, str]:
        """第一阶段构建全局类与 Mapper 符号索引 (短类名 -> 全限定名)"""
        symbol_map: Dict[str, str] = {}
        for f in java_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                pkg_match = self.PACKAGE_PATTERN.search(content)
                pkg = pkg_match.group(1) if pkg_match else ""
                for cm in self.CLASS_PATTERN.finditer(content):
                    cls_name = cm.group(2)
                    q_name = f"{pkg}.{cls_name}" if pkg else cls_name
                    symbol_map[cls_name] = q_name
            except Exception:
                continue

        # 扫描 MyBatis XML 中的 namespace 符号
        for root_str, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d.lower() not in {".git", "target", "build", "bin"}]
            for f in files:
                if f.endswith(".xml"):
                    try:
                        content = (Path(root_str) / f).read_text(encoding="utf-8", errors="ignore")
                        ns_match = self.MAPPER_XML_PATTERN.search(content)
                        if ns_match:
                            ns = ns_match.group(1).strip()
                            mapper_short = ns.split(".")[-1]
                            symbol_map[mapper_short] = ns
                    except Exception:
                        continue

        return symbol_map

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

        # 1. 建立项目级符号表
        global_symbols = self._build_global_symbol_table(java_files)

        for file_path in java_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                content = redact_secrets(content)
                rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
                lines = content.splitlines()

                pkg_match = self.PACKAGE_PATTERN.search(content)
                package_name = pkg_match.group(1) if pkg_match else ""

                # 收集当前文件的 import
                import_map: Dict[str, str] = {}
                for imp_match in self.IMPORT_PATTERN.finditer(content):
                    full_imp = imp_match.group(1).strip()
                    short_imp = full_imp.split(".")[-1]
                    import_map[short_imp] = full_imp

                current_annotations: List[str] = []
                current_class: Optional[str] = None
                class_role = "generic"
                class_start_line = 1
                class_request_path = ""
                injected_fields: Dict[str, str] = {}  # var_name -> TypeName

                current_method_mapping: Optional[Dict[str, str]] = None
                method_scopes: List[Dict[str, Any]] = []

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
                                m_end_line = self._compute_method_end_line(lines, idx)
                                method_scopes.append({
                                    "method_id": method_id,
                                    "name": m_name,
                                    "start_line": idx,
                                    "end_line": m_end_line,
                                })

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

                                # 仅当显式存在路由注解时才建立 API 实体，严禁对普通方法自动伪造 API
                                if current_method_mapping:
                                    m_verb = current_method_mapping["method"]
                                    sub_p = current_method_mapping["path"]
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

                # 符号解析辅助函数 (解析依赖类型至全限定 entity_id，防止链路断裂)
                def resolve_symbol(t_name: str) -> str:
                    if t_name in import_map:
                        return import_map[t_name]
                    if package_name:
                        cand = f"{package_name}.{t_name}"
                        if cand in global_symbols.values():
                            return cand
                    if t_name in global_symbols:
                        return global_symbols[t_name]
                    return t_name

                # 精确扫描方法作用域内的依赖调用 (杜绝广播到全类方法造成虚假调用)
                for var_name, type_name in injected_fields.items():
                    resolved_target_id = resolve_symbol(type_name)
                    call_pattern = re.compile(rf"\b{re.escape(var_name)}\.([a-zA-Z0-9_]+)\s*\(")
                    for match in call_pattern.finditer(content):
                        called_method = match.group(1)
                        call_line = content[:match.start()].count("\n") + 1

                        rel_type = "CALLS"
                        if "Mapper" in type_name or "Dao" in type_name:
                            rel_type = "CALLS_MAPPER"
                        elif "Service" in type_name:
                            rel_type = "CALLS_SERVICE"
                        elif "Repository" in type_name:
                            rel_type = "CALLS_REPOSITORY"

                        # 查找当前调用行属于哪个具体方法
                        enclosing_method = next(
                            (m for m in method_scopes if m["start_line"] <= call_line <= m["end_line"]),
                            None,
                        )

                        class_id = f"{package_name}.{current_class}" if package_name else (current_class or "UnknownClass")
                        source_id = enclosing_method["method_id"] if enclosing_method else class_id

                        # 仅为实际发生调用的实体挂载关系边
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=source_id,
                                relationship_type=rel_type,
                                target_entity_id=resolved_target_id,
                                confidence="strongly_inferred",
                                evidence=CodeEvidence(
                                    file_path=rel_path,
                                    start_line=call_line,
                                    snippet=match.group(0),
                                ),
                                metadata={"target_method": called_method},
                            )
                        )

            except Exception:
                continue

        return ScannerResult(entities=entities, relationships=relationships)

