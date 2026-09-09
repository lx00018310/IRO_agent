import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config
from iro_agent.security.policy import validate_read_path
from iro_agent.security.audit import AuditLogger


class CodeReader:
    """严格只读代码检索与查看工具"""

    def __init__(self, root_dir: Optional[str | Path] = None, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        raw_root = root_dir or self.config.project_root
        self.root_dir = validate_read_path(raw_root, self.config)
        self.audit = audit_logger or AuditLogger()

    def read_file(self, relative_path: str, start_line: int = 1, line_count: int = 200) -> str:
        """安全读取指定代码文件的片段（带行号）"""
        target_path = validate_read_path(self.root_dir / relative_path, self.config)
        if not target_path.is_file():
            raise FileNotFoundError(f"文件不存在: {target_path}")

        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            self.audit.record(
                tool_name="CodeReader",
                operation="read_file",
                target=str(target_path),
                result_summary=f"读取失败: {e}",
                status="ERROR",
            )
            raise

        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), start_idx + line_count)
        selected = lines[start_idx:end_idx]

        self.audit.record(
            tool_name="CodeReader",
            operation="read_file",
            target=str(target_path),
            result_summary=f"成功读取行 {start_idx + 1} 至 {end_idx}",
            status="SUCCESS",
        )

        formatted = []
        for idx, line in enumerate(selected, start=start_idx + 1):
            formatted.append(f"{idx:4d}: {line.rstrip()}")
        return "\n".join(formatted)

    def search_code(
        self,
        query: str,
        sub_dir: str = "",
        extensions: Optional[List[str]] = None,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """在只读代码目录中搜索关键字，支持按子目录与后缀过滤"""
        search_base = validate_read_path(self.root_dir / sub_dir, self.config)
        valid_exts = set(extensions) if extensions else {
            ".ts", ".js", ".vue", ".json", ".sql", ".py", ".md",
            ".java", ".kt", ".xml", ".yml", ".yaml", ".properties", ".env",
            ".sh", ".bat", ".ps1",
        }
        skip_dirs = {".git", "node_modules", "dist", ".cache", "cache"}

        from iro_agent.security.redactor import redact_secrets

        results = []
        for root, dirs, files in os.walk(search_base):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                ext = Path(file).suffix.lower()
                # 兼容 .env 文件的特殊命名
                if file.startswith(".env") or ext == ".env":
                    pass
                elif valid_exts and ext not in valid_exts:
                    continue
                file_path = Path(root) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, start=1):
                            if query.lower() in line.lower():
                                rel_path = str(file_path.relative_to(self.root_dir))
                                clean_content = redact_secrets(line.strip()[:200])
                                results.append({
                                    "file": rel_path,
                                    "line": line_no,
                                    "content": clean_content,
                                })
                                if len(results) >= max_results:
                                    break
                except Exception:
                    continue
            if len(results) >= max_results:
                break

        self.audit.record(
            tool_name="CodeReader",
            operation="search_code",
            target=f"query='{query}', base='{search_base}'",
            result_summary=f"匹配到 {len(results)} 条结果",
            status="SUCCESS",
        )
        return results

    def list_modules(self) -> List[Dict[str, str]]:
        """扫描项目主要模块目录"""
        modules = []
        for item in self.root_dir.iterdir():
            if item.is_dir() and not item.name.startswith((".", "node_modules")):
                modules.append({
                    "name": item.name,
                    "path": str(item.relative_to(self.root_dir)),
                })
        return modules
