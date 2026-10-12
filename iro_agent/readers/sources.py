"""One project's source inventory and shared read-only runtime adapters."""

import json
import os
from pathlib import Path
from typing import Optional

import requests

from iro_agent.config import IROConfig, get_config
from iro_agent.readers.code_reader import CodeReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.readers.log_reader import LogReader
from iro_agent.security.audit import AuditLogger
from iro_agent.security.redactor import redact_secrets
from iro_agent.security.policy import validate_read_path
from iro_agent.readers.limits import ReadBudget, iter_source_files

# Read-only text formats accepted by other_read; binaries are listed but never decoded.
OTHER_TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".log", ".json", ".jsonl", ".ndjson", ".geojson",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env",
    ".xml", ".html", ".htm", ".svg", ".css",
    ".csv", ".tsv", ".psv",
    ".sql", ".graphql", ".proto", ".openapi", ".swagger",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".java", ".kt", ".go", ".rs", ".c", ".h",
    ".cs", ".cpp", ".hpp", ".sh", ".bat", ".ps1", ".lua", ".rb", ".php", ".ipynb",
    ".pdf.name-only",
}
OTHER_MAX_BYTES = 2_000_000
OTHER_MAX_ENTRIES = 500


def is_other_text_file(path: Path) -> bool:
    if path.suffix.lower() in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
                               ".gz", ".tar", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
                               ".webp", ".ico", ".exe", ".dll", ".so", ".dylib", ".jar", ".class",
                               ".bin", ".dat", ".db", ".sqlite", ".sqlite3", ".woff", ".woff2", ".ttf", ".otf"}:
        return False
    if path.suffix.lower() in OTHER_TEXT_SUFFIXES:
        return True
    try:
        with path.open("rb") as stream:
            return b"\x00" not in stream.read(4096)
    except OSError:
        return False


def summarize_source_output(value, preview_chars=1200):
    """Bound data per source, preserving every source's identity and availability."""
    if not isinstance(value, dict) or "status" not in value or not isinstance(value.get("sources"), list):
        return value
    summary = {k: v for k, v in value.items() if k in {"status", "error", "project"}}
    summary["sources"] = []
    for source in value["sources"]:
        item = {}
        for key, data in source.items():
            if key in {"source_id", "description", "status", "error"}:
                item[key] = data
                continue
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            item[key] = data if len(serialized) <= preview_chars else {
                "preview": serialized[:preview_chars], "truncated": True,
                "record_count": len(data) if isinstance(data, list) else None,
            }
        summary["sources"].append(item)
    return summary


class SourceReaders:
    def __init__(self, config: Optional[IROConfig] = None, audit_logger=None):
        self.config = config or get_config()
        self.audit = audit_logger or AuditLogger(config=self.config)

    def inventory(self):
        """Never expose passwords, header values or model credentials to a planner."""
        sources = self.config.sources
        if sources is None:
            return {"project": self.config.project_name, "status": "SETUP_REQUIRED", "sources": []}
        items = []
        for kind in ("code", "logs", "databases", "http", "other"):
            for source in getattr(sources, kind):
                item = {"source_id": source.id, "kind": kind, "description": source.description}
                if kind in ("code", "logs"):
                    item["path"] = source.path
                elif kind == "databases":
                    item.update(type=source.type, host=source.host, port=source.port, database=source.database)
                elif kind == "other":
                    item["path"] = source.path
                else:
                    item["url"] = source.url
                items.append(item)
        return {"project": self.config.project_name, "sources": items,
                "setup_status": "COMPLETE" if self.config.is_setup_complete() else "SETUP_REQUIRED",
                "version_source_id": sources.code[0].id if sources.code else None,
                "query_guidance": "可用 source_id 精确选择来源；省略时分别查询该类全部来源。跨库不支持 SQL JOIN。"}

    def _clean(self, value):
        secrets = []
        if self.config.sources is not None:
            secrets = [s.password for s in self.config.sources.databases]
            secrets += [os.environ.get(s.password_env, "") for s in self.config.sources.databases if s.password_env]
            secrets += [os.environ.get(env, "") for s in self.config.sources.http for env in s.headers_env.values()]
        if isinstance(value, dict):
            return {k: ("[REDACTED_SECRET]" if v and k.lower() in {"password", "token", "api_key", "secret", "authorization", "cookie"}
                        else self._clean(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._clean(item) for item in value]
        if isinstance(value, str):
            for secret in sorted(set(secrets), key=len, reverse=True):
                if secret:
                    value = value.replace(secret, "[REDACTED_SECRET]")
            return redact_secrets(value)
        return value

    def _collect(self, kind, source_id, result_key, read):
        configured = getattr(self.config.sources, kind)
        selected = [s for s in configured if not source_id or s.id == source_id]
        groups, rows, errors = [], [], []
        for source in selected:
            try:
                result = read(source)
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(result["error"])
                group = {"source_id": source.id, "description": source.description,
                         "status": "OK", result_key: result}
                if isinstance(result, list):
                    for row in result:
                        item = dict(row) if isinstance(row, dict) else {"value": row}
                        if "source_id" in item:
                            item = {"record": item}
                        item["source_id"] = source.id
                        rows.append(item)
                else:
                    rows.append({**result, "source_id": source.id})
            except Exception as exc:
                group = {"source_id": source.id, "status": "UNAVAILABLE",
                         "error": f"observability_gap: {exc}"}
                errors.append(source.id)
            groups.append(group)
        output = {"status": "OK", result_key: rows, "sources": groups}
        if not selected:
            output.update(status="UNAVAILABLE", error=f"observability_gap: 未配置 {kind} 来源或未知来源 ID: {source_id or '(全部)'}")
        elif errors:
            output.update(status="PARTIAL" if len(errors) < len(selected) else "UNAVAILABLE",
                          error=f"observability_gap: 以下来源未能读取: {', '.join(errors)}")
        return self._clean(output)

    @staticmethod
    def _require_directory(path):
        if not Path(path).is_dir():
            raise FileNotFoundError(f"来源目录不存在: {path}")
        with os.scandir(path):
            pass

    def _other_file_content(self, path: Path, keyword: Optional[str], max_chars: int) -> dict:
        path = validate_read_path(path, self.config)
        if not is_other_text_file(path):
            return {"file": path.name, "binary": True,
                    "message": "二进制/文档文件仅列出位置，不做内容读取；如需检索请先导出为文本格式"}
        size = path.stat().st_size
        content = ReadBudget().read_text(path)
        if keyword:
            content = "\n".join(line for line in content.splitlines() if keyword.lower() in line.lower())
        return {"file": path.name, "size_bytes": size, "content": content[:max_chars],
                "truncated": len(content) > max_chars or size > OTHER_MAX_BYTES}

    def other_read(self, query: str = "", keyword: Optional[str] = None, file: str = "",
                   max_chars: int = 6000, source_id: Optional[str] = None, **kwargs):
        """Read registered arbitrary materials: list a directory or read one text file per source."""
        if not isinstance(max_chars, int) or not 1 <= max_chars <= 50000:
            raise ValueError("max_chars 必须是 1 到 50000 的整数")
        if self.config.sources is None:
            return {"status": "UNAVAILABLE", "error": "observability_gap: 当前为旧版单一来源配置，无其他资料来源"}
        target = (file or query or "").strip()
        if kwargs:
            return {"error": "其他资料来源只接受 query/keyword/file/max_chars/source_id 参数"}

        def read(source):
            root = Path(source.path)
            if root.is_file():
                if target and target != root.name:
                    raise FileNotFoundError(f"来源是单文件 {root.name}，找不到文件: {target}")
                return [self._other_file_content(root, keyword, max_chars)]

            def visible(path: Path) -> bool:
                return path.is_file() and not path.name.startswith(".") \
                    and "__pycache__" not in path.parts and "node_modules" not in path.parts
            files = sorted(p for p in iter_source_files(root, {"__pycache__", "node_modules"})
                           if visible(p) and p.resolve().is_relative_to(root.resolve()))
            matches = [p for p in files
                       if not target or target.lower() in p.name.lower()
                       or target in p.relative_to(root).as_posix()]
            if not matches:
                listing = [p.relative_to(root).as_posix() for p in files]
                raise FileNotFoundError(f"未找到匹配 '{target}' 的文件；可用文件: {', '.join(listing[:50])}")
            if len(matches) == 1:
                return [self._other_file_content(matches[0], keyword, max_chars)]
            return {"matches": [p.relative_to(root).as_posix() for p in matches[:100]],
                     "match_count": len(matches),
                     "hint": "多个文件匹配；请用 file 参数提供更完整的文件名或相对路径"}
        return self._collect("other", source_id, "documents", read)

    def code_search(self, query: str, source_id: Optional[str] = None, max_results: int = 50, **kwargs):
        if self.config.sources is None:
            return CodeReader(audit_logger=self.audit).search_code(query=query)

        def read(source):
            self._require_directory(source.path)
            return CodeReader(root_dir=source.path, audit_logger=self.audit, config=self.config).search_code(
                query=query, max_results=max_results)
        return self._collect("code", source_id, "matches", read)

    def code_read(self, file: str, start_line: int = 1, line_count: int = 200,
                  source_id: Optional[str] = None):
        def read(root):
            return {"file": file, "start_line": start_line, "line_count": line_count,
                    "content": CodeReader(root_dir=root, audit_logger=self.audit, config=self.config).read_file(
                        relative_path=file, start_line=start_line, line_count=line_count)}
        if self.config.sources is None:
            return self._clean(read(self.config.primary_code_root))
        return self._collect("code", source_id, "documents", lambda source: read(source.path))

    def log_search(self, keyword: str = "", query: str = "", limit: int = 20,
                   max_results: Optional[int] = None, source_id: Optional[str] = None, **kwargs):
        options = {k: v for k, v in kwargs.items() if k in {"level", "start_time", "end_time", "file_name_filter"}}
        count = max_results if max_results is not None else limit
        if self.config.sources is None:
            return LogReader(audit_logger=self.audit).search_logs(keyword=keyword or query, max_results=count, **options)

        def read(source):
            self._require_directory(source.path)
            return LogReader(log_dirs=[source.path], audit_logger=self.audit, config=self.config).search_logs(
                keyword=keyword or query, max_results=count, **options)
        return self._collect("logs", source_id, "logs", read)

    def _database(self, source):
        return DatabaseReader(db_config=source.connection_config(), audit_logger=self.audit)

    def db_query(self, sql: str = "", query: str = "", max_rows: int = 100,
                 source_id: Optional[str] = None, **kwargs):
        statement = sql or query
        if self.config.sources is None:
            return DatabaseReader(db_config=self.config.database, audit_logger=self.audit).execute_query(
                query=statement, max_rows=max_rows)
        return self._collect("databases", source_id, "rows", lambda s: self._database(s).execute_query(
            query=statement, max_rows=max_rows))

    def db_describe(self, table_name: str = "", table: str = "", source_id: Optional[str] = None, **kwargs):
        name = table_name or table
        if self.config.sources is None:
            return DatabaseReader(db_config=self.config.database, audit_logger=self.audit).describe_table(table_name=name)
        return self._collect("databases", source_id, "columns", lambda s: self._database(s).describe_table(table_name=name))

    def db_list_tables(self, source_id: Optional[str] = None):
        if self.config.sources is None:
            return DatabaseReader(db_config=self.config.database, audit_logger=self.audit).list_tables()
        return self._collect("databases", source_id, "tables", lambda s: self._database(s).list_tables())

    def _http_get(self, source, keyword=None, max_chars=4000):
        if not isinstance(max_chars, int) or not 1 <= max_chars <= 20000:
            raise ValueError("max_chars 必须是 1 到 20000 的整数")
        headers = {}
        for header, env_name in source.headers_env.items():
            if not os.environ.get(env_name):
                raise ValueError(f"缺少 HTTP 凭据环境变量 {env_name}")
            headers[header] = os.environ[env_name]
        # Exact registered endpoint; no redirects, browser, forms or method override.
        with requests.get(source.url, headers=headers, timeout=source.timeout,
                          allow_redirects=False, stream=True) as response:
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"HTTP {response.status_code}（不跟随重定向）")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=4096):
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_chars * 4:
                    break
            content = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            if keyword:
                content = "\n".join(line for line in content.splitlines() if keyword.lower() in line.lower())
            result = {"url": source.url, "status_code": response.status_code,
                      "content": content[:max_chars], "truncated": size >= max_chars * 4 or len(content) > max_chars}
        self.audit.record(tool_name="HttpSourceReader", operation="get", target=source.id,
                          result_summary=f"HTTP {result['status_code']}", status="SUCCESS")
        return result

    def web_fetch(self, url: str = "", source_id: Optional[str] = None,
                  keyword: Optional[str] = None, max_chars: int = 4000, **kwargs):
        if self.config.sources is None:
            from iro_agent.readers.web_reader import WebReader
            return WebReader(audit_logger=self.audit).fetch_page(url=url, keyword=keyword, **kwargs)
        configured = self.config.sources.http
        if url:
            matched = [s for s in configured if s.url == url and (not source_id or s.id == source_id)]
            if len(matched) != 1:
                return {"status": "UNAVAILABLE", "error": "observability_gap: URL 未登记或与 source_id 不一致"}
            source_id = matched[0].id
        if kwargs:
            return {"error": "只读 HTTP 来源不接受模式、账号、请求头或其他运行时覆盖参数"}
        return self._collect("http", source_id, "responses", lambda s: self._http_get(s, keyword, max_chars))

    def check(self):
        """Explicit user-requested health checks; PostgreSQL SELECT 1 / HTTP GET only."""
        groups = []
        if self.config.sources is None:
            return [{"status": "SETUP_REQUIRED"}]
        for kind in ("code", "logs", "databases", "http", "other"):
            for source in getattr(self.config.sources, kind):
                try:
                    if kind in ("code", "logs"):
                        self._require_directory(source.path)
                    elif kind == "databases":
                        self._database(source).execute_query(query="SELECT 1 AS alive", max_rows=1)
                    elif kind == "other":
                        root = Path(source.path)
                        if not (root.is_dir() or root.is_file()):
                            raise FileNotFoundError(f"来源路径不存在: {root}")
                        if root.is_dir():
                            with os.scandir(root):
                                pass
                    else:
                        self._http_get(source, max_chars=100)
                    groups.append({"source_id": source.id, "status": "OK"})
                except Exception as exc:
                    groups.append({"source_id": source.id, "status": "UNAVAILABLE", "error": str(exc)})
        return self._clean(groups)

    def tool_handlers(self):
        return {"sources_list": self.inventory, "code_search": self.code_search,
                "code_read": self.code_read,
                "log_search": self.log_search, "db_query": self.db_query,
                "db_describe": self.db_describe, "db_describe_table": self.db_describe,
                "db_list_tables": self.db_list_tables, "web_fetch": self.web_fetch,
                "other_read": self.other_read}
