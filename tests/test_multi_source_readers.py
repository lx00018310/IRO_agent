import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, MagicMock

import pytest
from pydantic import ValidationError

from iro_agent.config import HttpSourceConfig, OtherSourceConfig, SourcesConfig
from iro_agent.investigation.evaluator import EvidenceEvaluator
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import InvestigationStep, EvidenceTier
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.readers.sources import SourceReaders, summarize_source_output
from iro_agent.security.policy import SecurityPolicyError


def test_code_search_all_sources_distinguishes_same_file_names(project_config):
    for source in project_config.sources.code:
        (Path(source.path) / "app.py").write_text("dispatch = True\n", encoding="utf-8")
    result = SourceReaders(project_config).code_search("dispatch")
    assert result["status"] == "OK"
    assert {row["source_id"] for row in result["matches"]} == {"code_a", "code_b"}
    assert {row["file"] for row in result["matches"]} == {"app.py"}
    selected = SourceReaders(project_config).code_search("dispatch", source_id="code_b")
    assert len(selected["matches"]) == 1
    assert selected["matches"][0]["source_id"] == "code_b"


def test_logs_across_sources_preserve_full_file_provenance(project_config):
    for source in project_config.sources.logs:
        (Path(source.path) / "service.log").write_text("2026-10-11 12:00:00 ERROR timeout\n", encoding="utf-8")
    result = SourceReaders(project_config).log_search(keyword="timeout")
    assert len(result["logs"]) == 2
    assert len({row["source_file"] for row in result["logs"]}) == 2
    assert {row["source_id"] for row in result["logs"]} == {"logs_a", "logs_b"}


def test_db_queries_run_on_each_connection_and_support_targeting(project_config, monkeypatch):
    seen = []

    def execute(reader, query, max_rows):
        seen.append(reader.db_cfg.database)
        return [{"id": 1, "database": reader.db_cfg.database}]
    monkeypatch.setattr(DatabaseReader, "execute_query", execute)
    readers = SourceReaders(project_config)
    result = readers.db_query(sql="SELECT id FROM task")
    assert seen == ["db_a", "db_b"]
    assert {r["source_id"] for r in result["rows"]} == {"db_a", "db_b"}
    assert {r["database"] for r in result["rows"]} == {"db_a", "db_b"}
    seen.clear()
    assert readers.db_query(sql="SELECT id FROM task", source_id="db_b")["status"] == "OK"
    assert seen == ["db_b"]


def test_partial_failure_keeps_rows_and_is_an_observability_gap(project_config, monkeypatch):
    project_config.sources.databases[1].password_env = "SECOND_DB_PASSWORD"
    monkeypatch.setenv("SECOND_DB_PASSWORD", "sensitive-env-password")

    def execute(reader, query, max_rows):
        if reader.db_cfg.database == "db_b":
            raise OSError("offline sensitive-env-password")
        return [{"id": 1}]
    monkeypatch.setattr(DatabaseReader, "execute_query", execute)
    output = SourceReaders(project_config).db_query(sql="SELECT id FROM task")
    assert output["status"] == "PARTIAL"
    assert output["rows"] == [{"id": 1, "source_id": "db_a"}]
    assert "sensitive-env-password" not in json.dumps(output)
    step = InvestigationStep(step_id="multi", tool="db_query", tool_args={"sql": "SELECT id FROM task"},
                             evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, evidence_type="query", reason="检查全部数据库")
    evaluated = EvidenceEvaluator.evaluate_step(step, output)
    assert evaluated.verdict == "OBSERVABILITY_GAP"
    record = EvidenceEvaluator.create_evidence_record(step, output, evaluated)
    assert record.is_error and record.reliability == 0.0


def test_unknown_source_never_queries_default_database(project_config, monkeypatch):
    execute = Mock()
    monkeypatch.setattr(DatabaseReader, "execute_query", execute)
    output = SourceReaders(project_config).db_query(sql="SELECT 1", source_id="missing")
    assert output["status"] == "UNAVAILABLE"
    assert "observability_gap" in output["error"]
    execute.assert_not_called()


def test_empty_categories_do_not_use_legacy_paths_or_db(project_config, monkeypatch):
    project_config.sources = SourcesConfig()
    execute = Mock()
    monkeypatch.setattr(DatabaseReader, "execute_query", execute)
    readers = SourceReaders(project_config)
    assert readers.db_query(sql="SELECT 1")["status"] == "UNAVAILABLE"
    assert readers.code_search("x")["status"] == "UNAVAILABLE"
    assert readers.log_search(keyword="x")["status"] == "UNAVAILABLE"
    execute.assert_not_called()


def test_read_only_sql_guard_applies_to_all_sources(project_config, monkeypatch):
    import psycopg2
    connect = Mock(side_effect=AssertionError("write must not connect"))
    monkeypatch.setattr(psycopg2, "connect", connect)
    output = SourceReaders(project_config).db_query(sql="DELETE FROM task")
    assert output["status"] == "UNAVAILABLE"
    assert len(output["sources"]) == 2
    connect.assert_not_called()


def test_inventory_and_redaction_hide_source_credentials(project_config):
    readers = SourceReaders(project_config)
    inventory = json.dumps(readers.inventory())
    assert "source-secret" not in inventory
    value = readers._clean({"source_id": "db_a", "password": "x", "items": [{"message": "source-secret-db_a"}]})
    assert value["source_id"] == "db_a"
    assert value["password"] == "[REDACTED_SECRET]"
    assert "source-secret" not in json.dumps(value)


def test_disappeared_code_source_reports_partial_gap(project_config):
    (Path(project_config.sources.code[0].path) / "app.py").write_text("dispatch = True", encoding="utf-8")
    Path(project_config.sources.code[1].path).rmdir()
    output = SourceReaders(project_config).code_search("dispatch")
    assert output["status"] == "PARTIAL"
    assert len(output["matches"]) == 1
    assert output["sources"][1]["status"] == "UNAVAILABLE"


@pytest.fixture
def http_server():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/forbidden")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"path": self.path, "echo": self.headers.get("Authorization", "")}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()
    server.server_close()
    thread.join()


def test_http_all_sources_use_get_and_hide_header_values(project_config, monkeypatch, http_server):
    base, hits = http_server
    monkeypatch.setenv("TEST_AUTH", "Bearer private-header-secret")
    project_config.sources.http = [HttpSourceConfig(id=name, description=name, url=base + path,
                                  headers_env={"Authorization": "TEST_AUTH"}) for name, path in (("status", "/status"), ("queue", "/queue"))]
    readers = SourceReaders(project_config)
    output = readers.web_fetch()
    assert output["status"] == "OK"
    assert len(output["responses"]) == 2
    assert {(method, path) for method, path, _ in hits} == {("GET", "/status"), ("GET", "/queue")}
    assert all(header == "Bearer private-header-secret" for _, _, header in hits)
    assert "private-header-secret" not in json.dumps(output)
    assert "private-header-secret" not in json.dumps(readers.inventory())


def test_http_rejects_unregistered_url_id_mismatch_and_runtime_overrides(project_config, http_server):
    base, hits = http_server
    project_config.sources.http = [HttpSourceConfig(id="status", description="status", url=base + "/status")]
    readers = SourceReaders(project_config)
    for kwargs in ({"url": base + "/status/"}, {"url": base + "/status", "source_id": "other"},
                   {"source_id": "status", "mode": "browser"}, {"source_id": "status", "headers": {}}):
        assert "error" in readers.web_fetch(**kwargs)
    assert hits == []


def test_http_does_not_follow_redirect(project_config, http_server):
    base, hits = http_server
    project_config.sources.http = [HttpSourceConfig(id="redirect", description="redirect", url=base + "/redirect")]
    output = SourceReaders(project_config).web_fetch(source_id="redirect")
    assert output["status"] == "UNAVAILABLE"
    assert [(method, path) for method, path, _ in hits] == [("GET", "/redirect")]


@pytest.mark.parametrize("url", ["file:///secret", "data:text/html,secret", "http://user:password@host/path", "http://host/?token=secret", "http://host/#fragment"])
def test_unsafe_http_config_is_rejected(url):
    with pytest.raises(ValidationError):
        HttpSourceConfig(id="http", description="test", url=url)


def test_missing_http_env_does_not_make_request(project_config, http_server):
    base, hits = http_server
    project_config.sources.http = [HttpSourceConfig(id="status", description="status", url=base + "/status", headers_env={"Authorization": "MISSING_TEST_AUTH"})]
    assert SourceReaders(project_config).web_fetch()["status"] == "UNAVAILABLE"
    assert hits == []


@pytest.fixture
def other_sources(project_config):
    docs = project_config.sources.other
    api_doc = Path(project_config.sources.code[0].path).parent / "docs_a"
    exports = Path(project_config.sources.code[0].path).parent / "docs_b"
    api_doc.mkdir(exist_ok=True)
    exports.mkdir(exist_ok=True)
    (api_doc / "api.md").write_text("# API 手册\nGET /orders 查询订单\nGET /dispatch 调度接口\n", encoding="utf-8")
    (api_doc / "data-dict.md").write_text("# 数据字典\ntask 表记录月台任务\n", encoding="utf-8")
    (api_doc / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nbinary")
    (exports / "orders-export.csv").write_text("order_id,status\n1,done\n", encoding="utf-8")
    docs.append(OtherSourceConfig(id="docs_a", description="接口文档目录", path=str(api_doc)))
    docs.append(OtherSourceConfig(id="docs_b", description="导出数据", path=str(exports / "orders-export.csv")))
    return api_doc, exports


def test_other_read_lists_then_reads_selected_file_per_source(project_config, other_sources):
    api_doc, _ = other_sources
    readers = SourceReaders(project_config)
    single = readers.other_read(query="api", source_id="docs_a")
    assert single["status"] == "OK"
    assert "GET /orders 查询订单" in single["documents"][0]["content"]
    assert single["documents"][0]["file"] == "api.md"
    multiple = readers.other_read(source_id="docs_a")
    assert multiple["documents"][0]["match_count"] == 3
    assert "logo.png" in multiple["documents"][0]["matches"]
    binary = readers.other_read(query="logo", source_id="docs_a")
    assert binary["documents"][0]["binary"] is True
    assert "content" not in binary["documents"][0]
    keyword = readers.other_read(query="api", keyword="dispatch", source_id="docs_a")
    assert "GET /dispatch 调度接口" in keyword["documents"][0]["content"]
    assert "GET /orders 查询订单" not in keyword["documents"][0]["content"]
    assert (api_doc / "logo.png").exists()


def test_other_read_single_file_source_and_cross_source_isolation(project_config, other_sources):
    readers = SourceReaders(project_config)
    exported = readers.other_read(source_id="docs_b")
    assert exported["status"] == "OK"
    assert "order_id,status" in exported["documents"][0]["content"]
    wrong = readers.other_read(source_id="docs_b", file="api.md")
    assert wrong["status"] == "UNAVAILABLE"
    assert "observability_gap" in wrong["error"]
    both = readers.other_read()
    assert {row["source_id"] for row in both["documents"]} == {"docs_a", "docs_b"}


def test_other_read_reports_gap_for_unknown_source_or_missing_file(project_config):
    readers = SourceReaders(project_config)
    assert readers.other_read(source_id="missing")["status"] == "UNAVAILABLE"
    project_config.sources.other.append(OtherSourceConfig(id="docs", description="d", path="Z:/definitely/not/here"))
    missing = readers.other_read(source_id="docs")
    assert missing["status"] == "UNAVAILABLE"
    assert missing["sources"][0]["status"] == "UNAVAILABLE"


def test_other_source_rejects_relative_path_and_duplicates(project_config):
    with pytest.raises(ValidationError):
        OtherSourceConfig(id="rel", description="d", path="docs/api.md")
    with pytest.raises(ValidationError, match="ID 重复"):
        SourcesConfig(code=[{"id": "x", "description": "c", "path": str(Path(project_config.sources.code[0].path))}],
                      other=[{"id": "X", "description": "o", "path": str(Path(project_config.sources.code[0].path))}])


def test_chat_and_harness_use_same_multi_source_adapters(project_config):
    from iro_agent.cli import init_agent_engine
    for source in project_config.sources.code:
        (Path(source.path) / "app.py").write_text("dispatch = True", encoding="utf-8")
    client = init_agent_engine(project_config)
    harness = InvestigationHarness(planner_mode="deterministic")
    expected = client.tool_handlers["code_search"](query="dispatch")
    assert harness.tool_handlers["code_search"](query="dispatch") == expected
    assert len(expected["matches"]) == 2
    assert "sources_list" in harness.tool_registry.list_tool_names()
    assert "code_b" in harness.tool_registry.get_prompt_description()
    assert "source-secret" not in harness.tool_registry.get_prompt_description()
    for schema in client.tools_schema:
        if schema["function"]["name"] in {"code_search", "db_query", "log_search", "web_fetch", "other_read"}:
            assert "source_id" in schema["function"]["parameters"]["properties"]


def test_large_first_source_does_not_hide_later_source_failure_from_planner(project_config):
    from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
    from iro_agent.investigation.models import Hypothesis
    value = {"status": "PARTIAL", "error": "observability_gap: db_b unavailable", "rows": [], "sources": [
        {"source_id": "db_a", "status": "OK", "rows": [{"content": "x" * 10000}]},
        {"source_id": "db_b", "status": "UNAVAILABLE", "error": "observability_gap: timeout"},
    ]}
    summary = summarize_source_output(value)
    assert summary["sources"][0]["rows"]["truncated"] is True
    assert summary["sources"][1]["source_id"] == "db_b"
    assert summary["sources"][1]["status"] == "UNAVAILABLE"
    step = InvestigationStep(step_id="sources", tool="db_query", tool_args={"sql": "SELECT 1"},
                             evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, evidence_type="db_query", reason="all sources")
    evaluated = EvidenceEvaluator.evaluate_step(step, value)
    record = EvidenceEvaluator.create_evidence_record(step, value, evaluated)
    planner = LLMInvestigationPlanner(glm_client=Mock())
    prompt = planner._build_prompt("test", [Hypothesis(hypothesis_id="H1", description="test")], [record], 5)
    assert '"source_id": "db_b"' in prompt
    assert "timeout" in prompt and "UNAVAILABLE" in prompt


def test_fact_query_model_context_keeps_all_sources_after_large_first_result(project_config, monkeypatch):
    from iro_agent.llm.glm_client import GlmClient
    client = GlmClient()
    client.register_tool_handler("db_query", lambda **_: {"status": "OK", "rows": [], "sources": [
        {"source_id": "db_a", "status": "OK", "rows": [{"content": "x" * 10000}]},
        {"source_id": "db_b", "status": "OK", "rows": [{"status": "SECOND_SOURCE_RESULT"}]},
    ]})
    responses = [
        {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "read", "function": {"name": "db_query", "arguments": '{"query": "SELECT 1"}'}}]}}]},
        {"choices": [{"message": {"content": "done"}}]},
    ]
    sent = []

    def post(*args, **kwargs):
        sent.append(json.loads(json.dumps(kwargs["json"])))
        response = Mock(status_code=200)
        response.json.return_value = responses.pop(0)
        return response
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    assert client.chat_completion([{"role": "user", "content": "查全部来源"}]) == "done"
    tool_message = [m for m in sent[1]["messages"] if m["role"] == "tool"][0]
    parsed = json.loads(tool_message["content"])
    assert parsed["sources"][1]["rows"][0]["status"] == "SECOND_SOURCE_RESULT"


def test_db_connections_remain_read_only_and_close_for_each_source(project_config, monkeypatch):
    import psycopg2
    connections, parameters = [], []

    def connect(**kwargs):
        parameters.append(kwargs)
        connection = Mock()
        connection.cursor.return_value = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchmany.return_value = [{"database": kwargs["dbname"]}]
        connections.append(connection)
        return connection
    monkeypatch.setattr(psycopg2, "connect", connect)
    output = SourceReaders(project_config).db_query(sql="SELECT database FROM task")
    assert output["status"] == "OK"
    assert [p["dbname"] for p in parameters] == ["db_a", "db_b"]
    for connection in connections:
        connection.set_session.assert_called_once_with(readonly=True, autocommit=False)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


def test_source_id_column_in_business_row_is_preserved(project_config, monkeypatch):
    monkeypatch.setattr(DatabaseReader, "execute_query", lambda *args, **kwargs: [{"source_id": "business-origin", "id": 1}])
    result = SourceReaders(project_config).db_query(sql="SELECT source_id, id FROM task", source_id="db_a")
    assert result["rows"][0]["source_id"] == "db_a"
    assert result["rows"][0]["record"]["source_id"] == "business-origin"


def test_selected_code_source_cannot_traverse_into_another_allowed_source(project_config):
    from iro_agent.readers.code_reader import CodeReader
    first, second = project_config.sources.code
    (Path(second.path) / "app.py").write_text("private source", encoding="utf-8")
    reader = CodeReader(root_dir=first.path, config=project_config)
    with pytest.raises(SecurityPolicyError):
        reader.read_file("../code_b/app.py")


def test_static_scanner_cannot_read_outside_its_source(project_config):
    from iro_agent.knowledge.scanners.python import PythonScanner
    first, second = project_config.sources.code
    outside = Path(second.path) / "app.py"
    outside.write_text("private source", encoding="utf-8")
    with pytest.raises(PermissionError):
        PythonScanner(Path(first.path)).read_source_file(outside)
