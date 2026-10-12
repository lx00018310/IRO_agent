from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.config import get_config, IROConfig
from iro_agent.security.policy import validate_read_path, SecurityPolicyError
from iro_agent.security.audit import AuditLogger
from iro_agent.security.redactor import redact_secrets
from iro_agent.readers.limits import (
    ReadBudget, ReadLimitError, bounded_int, iter_source_files,
    MAX_RESULTS, MAX_READ_LINES, MAX_OUTPUT_CHARS,
)


class CodeReader:
    """严格只读代码检索与查看工具"""

    def __init__(self, root_dir: Optional[str | Path] = None, audit_logger: Optional[AuditLogger] = None,
                 config: Optional[IROConfig] = None):
        self.config = config or get_config()
        raw_root = root_dir or self.config.primary_code_root
        if not raw_root:
            raise ValueError("未配置代码来源")
        self.root_dir = validate_read_path(raw_root, self.config)
        self.audit = audit_logger or AuditLogger()

    def read_file(self, relative_path: str, start_line: int = 1, line_count: int = 200) -> str:
        """安全读取指定代码文件的片段（带行号）"""
        bounded_int(start_line, "start_line", 100000)
        bounded_int(line_count, "line_count", MAX_READ_LINES)
        if not relative_path or Path(relative_path).is_absolute():
            raise SecurityPolicyError("代码文件必须使用所选来源内的相对路径")
        target_path = validate_read_path(self.root_dir / relative_path, self.config)
        if not target_path.is_relative_to(self.root_dir):
            raise SecurityPolicyError("代码文件不能越出所选来源目录")
        if not target_path.is_file():
            raise FileNotFoundError(f"文件不存在: {target_path}")

        try:
            lines = ReadBudget().read_text(target_path).splitlines()
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
        content = redact_secrets("\n".join(formatted))
        if len(content) > MAX_OUTPUT_CHARS:
            raise ReadLimitError("observability_gap: 阅读片段超过输出上限，请减少 line_count")
        return content

    def search_code(
        self,
        query: str,
        sub_dir: str = "",
        extensions: Optional[List[str]] = None,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """在只读代码目录中搜索关键字，支持按子目录与后缀过滤"""
        bounded_int(max_results, "max_results", MAX_RESULTS)
        search_base = validate_read_path(self.root_dir / sub_dir, self.config)
        if not search_base.is_relative_to(self.root_dir):
            raise SecurityPolicyError("代码搜索不能越出所选来源目录")
        valid_exts = set(extensions) if extensions else {
            ".ts", ".js", ".vue", ".json", ".sql", ".py", ".md",
            ".java", ".kt", ".xml", ".yml", ".yaml", ".properties", ".env",
            ".sh", ".bat", ".ps1", ".cs", ".config", ".csproj",
        }
        skip_dirs = {".git", "node_modules", "dist", ".cache", "cache"}

        results = []
        budget = ReadBudget()
        for file_path in iter_source_files(search_base, skip_dirs):
            if len(results) >= max_results:
                break
            file = file_path.name
            ext = file_path.suffix.lower()
            if not file.startswith(".env") and valid_exts and ext not in valid_exts:
                continue
            try:
                resolved = validate_read_path(file_path, self.config)
                if not resolved.is_relative_to(self.root_dir):
                    continue
                for line_no, line in enumerate(budget.read_text(resolved).splitlines(), start=1):
                    if query.lower() in line.lower():
                        results.append({"file": str(file_path.relative_to(self.root_dir)), "line": line_no,
                                        "content": redact_secrets(line.strip()[:200])})
                        if len(results) >= max_results:
                            break
            except ReadLimitError:
                raise
            except OSError:
                continue

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
