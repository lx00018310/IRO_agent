import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.scanners.base import BaseCodeScannerAdapter, ScannerResult
from iro_agent.knowledge.code_entities import CodeEntityNode, CodeRelationshipEdge, CodeEvidence
from iro_agent.security.redactor import redact_secrets


class VueFrontendScanner(BaseCodeScannerAdapter):
    """轻量级 Vue / 前端 API 调用与组件依赖扫描器"""

    # 正则提取 axios/request 请求
    API_CALL_PATTERN = re.compile(
        r"(?:axios|request|http)\s*\.\s*(get|post|put|delete)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
        re.IGNORECASE,
    )
    FUNCTION_DEF_PATTERN = re.compile(
        r"(?:export\s+)?(?:const|function)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^\)]*\)\s*=>|function\s+([a-zA-Z0-9_]+)\s*\("
    )
    VUE_IMPORT_PATTERN = re.compile(
        r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]"
    )

    def detect(self) -> bool:
        """检查是否存在 package.json 或 .vue 文件"""
        if (self.project_root / "package.json").exists():
            return True
        for root_str, _, files in os.walk(self.project_root):
            for f in files:
                if f.endswith(".vue"):
                    return True
        return False

    def scan(self) -> ScannerResult:
        entities: List[CodeEntityNode] = []
        relationships: List[CodeRelationshipEdge] = []

        candidate_files: List[Path] = []
        for root_str, dirs, files in os.walk(self.project_root):
            dirs[:] = [
                d for d in dirs
                if d.lower() not in {".git", "node_modules", "dist", "build", ".idea", ".vscode"}
            ]
            for f in files:
                if f.endswith((".js", ".ts", ".vue")):
                    candidate_files.append(Path(root_str) / f)

        # 1. 扫描 API 声明文件 (通常在 api/ 目录下或包含 api 字样)
        for file_path in candidate_files:
            rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                content = redact_secrets(content)

                if file_path.suffix.lower() == ".vue":
                    # Vue 组件
                    comp_name = file_path.stem
                    comp_id = f"vue:{comp_name}"
                    entities.append(
                        CodeEntityNode(
                            entity_id=comp_id,
                            entity_type="controller",  # 前端视图控制器
                            name=comp_name,
                            qualified_name=comp_name,
                            file_path=rel_path,
                            framework="vue",
                        )
                    )
                    # 匹配 import 的前端 API 函数并建边
                    for imp_match in self.VUE_IMPORT_PATTERN.finditer(content):
                        names = imp_match.group(1).split(",")
                        for n in names:
                            fn_name = n.strip()
                            if fn_name:
                                relationships.append(
                                    CodeRelationshipEdge(
                                        source_entity_id=comp_id,
                                        relationship_type="CALLS",
                                        target_entity_id=f"frontend_api:{fn_name}",
                                        confidence="inferred",
                                    )
                                )
                    continue

                # JS/TS API 接口封装文件
                lines = content.splitlines()
                current_fn = None
                for idx, line in enumerate(lines, 1):
                    fn_match = self.FUNCTION_DEF_PATTERN.search(line)
                    if fn_match:
                        current_fn = fn_match.group(1) or fn_match.group(2)

                    api_match = self.API_CALL_PATTERN.search(line)
                    if api_match:
                        http_method = api_match.group(1).upper()
                        api_url = api_match.group(2).split("?")[0].strip()
                        fn_id = f"frontend_api:{current_fn}" if current_fn else f"frontend_api:{idx}"

                        entities.append(
                            CodeEntityNode(
                                entity_id=fn_id,
                                entity_type="api",
                                name=current_fn or f"{http_method} {api_url}",
                                file_path=rel_path,
                                start_line=idx,
                                framework="vue",
                                metadata={"url": api_url, "method": http_method},
                            )
                        )

                        # 与后端 API 建立连接 (模糊匹配 api:METHOD:path)
                        backend_api_id = f"api:{http_method}:{api_url}"
                        relationships.append(
                            CodeRelationshipEdge(
                                source_entity_id=fn_id,
                                relationship_type="CALLS",
                                target_entity_id=backend_api_id,
                                confidence="strongly_inferred",
                                evidence=CodeEvidence(
                                    file_path=rel_path,
                                    start_line=idx,
                                    snippet=line.strip(),
                                ),
                            )
                        )

            except Exception:
                continue

        return ScannerResult(entities=entities, relationships=relationships)
