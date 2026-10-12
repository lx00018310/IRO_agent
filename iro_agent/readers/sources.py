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
        self.audit = audit_logger or AuditLogger(db_path=self.config.storage.audit_db_path)

    def inventory(self):
        """Never expose passwords, header values or model credentials to a planner."""
        sources = self.config.sources
        if sources is None:
            return {"project": self.config.project_name, "status": "SETUP_REQUIRED", "sources": []}
        items = []
        for kind in ("code", "logs", "databases", "http"):
            for source in getattr(sources, kind):
                item = {"source_id": source.id, "kind": kind, "description": source.description}
                if kind in ("code", "logs"):
                    item["path"] = source.path
                elif kind == "databases":
                    item.update(host=source.host, port=source.port, database=source.database)
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

    def code_search(self, query: str, source_id: Optional[str] = None, max_results: int = 50, **kwargs):
        if self.config.sources is None:
            return CodeReader(audit_logger=self.audit).search_code(query=query)

        def read(source):
            self._require_directory(source.path)
            return CodeReader(root_dir=source.path, audit_logger=self.audit, config=self.config).search_code(
                query=query, max_results=max_results)
        return self._collect("code", source_id, "matches", read)

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
        for kind in ("code", "logs", "databases", "http"):
            for source in getattr(self.config.sources, kind):
                try:
                    if kind in ("code", "logs"):
                        self._require_directory(source.path)
                    elif kind == "databases":
                        self._database(source).execute_query(query="SELECT 1 AS alive", max_rows=1)
                    else:
                        self._http_get(source, max_chars=100)
                    groups.append({"source_id": source.id, "status": "OK"})
                except Exception as exc:
                    groups.append({"source_id": source.id, "status": "UNAVAILABLE", "error": str(exc)})
        return self._clean(groups)

    def tool_handlers(self):
        return {"sources_list": self.inventory, "code_search": self.code_search,
                "log_search": self.log_search, "db_query": self.db_query,
                "db_describe": self.db_describe, "db_describe_table": self.db_describe,
                "db_list_tables": self.db_list_tables, "web_fetch": self.web_fetch}
