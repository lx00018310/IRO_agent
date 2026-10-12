import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, call

import pytest

from iro_agent.config import DatabaseConfig, DatabaseSourceConfig, IROConfig, OtherSourceConfig
from iro_agent.gateway.dedup import EventDeduplicator
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.knowledge.schema_scanner import SchemaScanner
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.llm.glm_client import GlmClient
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.memory.learning_store import LearningMemoryStore
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.sources import SourceReaders
from iro_agent.security.audit import AuditLogger
from iro_agent.security.policy import SecurityPolicyError, agent_data_dir, validate_write_path


@pytest.mark.parametrize("factory", [AuditLogger, IncidentStore, LearningMemoryStore, EventDeduplicator])
def test_sqlite_output_is_confined_and_custom_outside_path_is_rejected(project_config, tmp_path, factory):
    store = factory()
    assert Path(store.db_path).is_relative_to(agent_data_dir(project_config))
    outside = tmp_path / "production" / "business.db"
    with pytest.raises(SecurityPolicyError):
        factory(str(outside))
    assert not outside.parent.exists()


def test_workspace_unavailable_never_falls_back_to_cwd(tmp_path):
    for cfg in (IROConfig(), IROConfig(project_root=str(tmp_path / "missing"))):
        with pytest.raises(SecurityPolicyError):
            ProjectKnowledgeStore(config=cfg)
    assert not (Path.cwd() / ".iro_agent" / "missing-output.json").exists()


def test_write_traversal_and_junction_escape_are_blocked(project_config, tmp_path):
    root = agent_data_dir(project_config)
    root.mkdir()
    outside = tmp_path / "production"
    outside.mkdir()
    with pytest.raises(SecurityPolicyError):
        validate_write_path("../production/overwrite.txt", project_config)
    link = root / "linked"
    if os.name == "nt":
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True)
        assert result.returncode == 0
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecurityPolicyError):
        validate_write_path(link / "overwrite.txt", project_config)
    assert not (outside / "overwrite.txt").exists()


def test_data_root_itself_cannot_be_a_junction(project_config, tmp_path):
    root = agent_data_dir(project_config)
    outside = tmp_path / "production"
    outside.mkdir()
    if os.name == "nt":
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(root), str(outside)], capture_output=True)
        assert result.returncode == 0
    else:
        root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecurityPolicyError):
        AuditLogger()
    assert list(outside.iterdir()) == []


def test_csharp_search_segment_read_and_both_agent_entrypoints(project_config):
    source = project_config.sources.code[0]
    root = Path(source.path)
    (root / "Task.cs").write_text("class Task {\n  void Dispatch() {}\n}\n", encoding="utf-8")
    (root / "App.exe.config").write_text('<add key="Dispatch" value="true" />', encoding="utf-8")
    readers = SourceReaders(project_config)
    matches = readers.code_search("Dispatch", source_id=source.id)
    assert {m["file"] for m in matches["matches"]} == {"Task.cs", "App.exe.config"}
    read = readers.code_read(file="Task.cs", start_line=2, line_count=1, source_id=source.id)
    assert read["documents"][0]["content"] == "   2:   void Dispatch() {}"
    assert "class Task" not in read["documents"][0]["content"]
    from iro_agent.cli import init_agent_engine
    client = init_agent_engine(project_config)
    harness = InvestigationHarness(planner_mode="deterministic")
    for handlers in (client.tool_handlers, harness.tool_handlers):
        assert handlers["code_read"](file="Task.cs", start_line=2, line_count=1, source_id=source.id) == read
    assert "code_read" in harness.tool_registry.list_tool_names()
    schema = next(t["function"] for t in client.tools_schema if t["function"]["name"] == "code_read")
    assert "source_id" in schema["parameters"]["properties"]


def test_code_read_rejects_escape_and_redacts_secrets(project_config):
    source = project_config.sources.code[0]
    (Path(source.path) / "App.config").write_text("password=secret123456", encoding="utf-8")
    readers = SourceReaders(project_config)
    assert "secret123456" not in str(readers.code_read(file="App.config", source_id=source.id))
    for file, count in (("../code_b/app.py", 1), ("App.config", 501), ("App.config", -1)):
        result = readers.code_read(file=file, line_count=count, source_id=source.id)
        assert result["status"] == "UNAVAILABLE"


def test_read_limits_report_gap_instead_of_empty_success(project_config, monkeypatch):
    import iro_agent.readers.limits as limits
    source = project_config.sources.code[0]
    root = Path(source.path)
    (root / "Large.cs").write_text("class X {}" * 20, encoding="utf-8")
    monkeypatch.setattr(limits, "MAX_FILE_BYTES", 100)
    output = SourceReaders(project_config).code_search("X", source_id=source.id)
    assert output["status"] == "UNAVAILABLE"
    assert "读取大小上限" in output["sources"][0]["error"]


def test_other_enumeration_is_bounded_before_sorting(project_config, monkeypatch):
    import iro_agent.readers.limits as limits
    root = Path(project_config.sources.code[0].path)
    for i in range(4):
        (root / f"{i}.txt").write_text("text", encoding="utf-8")
    project_config.sources.other.append(OtherSourceConfig(id="docs", description="docs", path=str(root)))
    monkeypatch.setattr(limits, "MAX_SCAN_FILES", 2)
    result = SourceReaders(project_config).other_read(source_id="docs")
    assert result["status"] == "UNAVAILABLE"
    assert "扫描数量" in result["sources"][0]["error"]


def test_mysql_default_port_and_source_connection_config():
    source = DatabaseSourceConfig(id="mysql", description="orders", type="mysql", host="localhost",
                                  user="reader", database="orders", query_timeout=3)
    assert source.port == source.connection_config().port == 3306
    assert source.connection_config().type == "mysql"
    assert source.connection_config().query_timeout == 3
    assert DatabaseConfig().port == 5432


def test_mysql_readonly_timeout_bounded_query_and_cleanup(project_config, monkeypatch):
    import pymysql
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchmany.return_value = [{"id": 1, "created_at": datetime(2026, 10, 12)}]
    connect = Mock(return_value=connection)
    monkeypatch.setattr(pymysql, "connect", connect)
    cfg = DatabaseConfig(type="mysql", host="localhost", user="readonly", database="orders", query_timeout=3)
    rows = DatabaseReader(cfg).execute_query("SELECT id, created_at FROM task WHERE id = %s", (1,), max_rows=5)
    assert rows[0]["created_at"] == "2026-10-12T00:00:00"
    assert cursor.execute.call_args_list == [
        call("SET SESSION max_execution_time = %s", (3000,)),
        call("START TRANSACTION READ ONLY"),
        call("SELECT * FROM (\nSELECT id, created_at FROM task WHERE id = %s\n) AS iro_read LIMIT %s", (1, 5)),
    ]
    assert connect.call_args.kwargs["read_timeout"] == 3
    assert connect.call_args.kwargs["local_infile"] is False
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    connection.commit.assert_not_called()


def test_mysql_failure_to_set_guards_never_executes_query(project_config, monkeypatch):
    import pymysql
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("server does not support timeout setting")
    monkeypatch.setattr(pymysql, "connect", lambda **_: connection)
    cfg = DatabaseConfig(type="mysql", host="localhost", user="readonly", database="orders")
    with pytest.raises(RuntimeError):
        DatabaseReader(cfg).execute_query("SELECT * FROM task")
    assert cursor.execute.call_count == 1
    connection.close.assert_called_once()


@pytest.mark.parametrize("sql", ["SELECT 1 INTO OUTFILE 'x'", "SELECT LOAD_FILE('x')", "SELECT SLEEP(30)",
                                "SELECT /*!50000 SLEEP(30) */ 1", "SELECT /*+ MAX_EXECUTION_TIME(0) */ 1",
                                "SELECT 1; DELETE FROM task", "UPDATE task SET state=1"])
def test_mysql_write_and_limit_bypasses_rejected_before_connect(project_config, monkeypatch, sql):
    import pymysql
    connect = Mock()
    monkeypatch.setattr(pymysql, "connect", connect)
    with pytest.raises(SecurityPolicyError):
        DatabaseReader(DatabaseConfig(type="mysql")).execute_query(sql)
    connect.assert_not_called()


def test_mysql_metadata_uses_database_schema(project_config):
    reader = DatabaseReader(DatabaseConfig(type="mysql", host="h", user="u", database="orders"))
    reader.execute_query = Mock(return_value=[])
    reader.list_tables()
    assert reader.execute_query.call_args.kwargs["params"] == ("orders",)
    reader.describe_table("task")
    assert reader.execute_query.call_args.kwargs["params"] == ("orders", "task")
    assert "column_key" in reader.execute_query.call_args.args[0]
    reader.get_foreign_keys("task")
    assert "referenced_table_name" in reader.execute_query.call_args.args[0]
    scanner = SchemaScanner(reader.db_cfg)
    scanner.reader.execute_query = Mock(return_value=[])
    assert scanner.scan().connected
    assert scanner.reader.execute_query.call_args.kwargs["params"] == ("orders",)


def test_git_output_parameter_is_rejected_before_process_creation(project_config, monkeypatch, tmp_path):
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    reader = GitReader(repo_dir=project_config.sources.code[0].path, audit_logger=Mock())
    outside = tmp_path / "production.txt"
    with pytest.raises(SecurityPolicyError):
        reader.get_diff("--output=" + str(outside), "HEAD")
    run.assert_not_called()
    assert not outside.exists()


def test_code_read_segment_reaches_model_without_search_preview_truncation(project_config, monkeypatch):
    source = project_config.sources.code[0]
    content = "\n".join(f"// line {i}: " + "x" * 60 for i in range(60))
    (Path(source.path) / "Task.cs").write_text(content, encoding="utf-8")
    client = GlmClient()
    client.register_tool_handler("code_read", SourceReaders(project_config).code_read)
    responses = [
        {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [{
            "id": "read", "function": {"name": "code_read", "arguments": json.dumps({
                "file": "Task.cs", "line_count": 60, "source_id": source.id})}}]}}]},
        {"choices": [{"message": {"content": "done"}}]},
    ]
    sent = []
    def post(*args, **kwargs):
        sent.append(json.loads(json.dumps(kwargs["json"])))
        response = Mock(status_code=200)
        response.json.return_value = responses.pop(0)
        return response
    monkeypatch.setattr("iro_agent.llm.glm_client.requests.post", post)
    assert client.chat_completion([{"role": "user", "content": "read Task.cs"}]) == "done"
    tool_message = next(m for m in sent[1]["messages"] if m["role"] == "tool")
    assert "line 59:" in tool_message["content"]


def test_git_valid_refs_still_compare_readonly(project_config, tmp_path):
    repo = Path(project_config.sources.code[0].path)
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    def git(*args):
        return subprocess.run(["git", "-c", f"core.hooksPath={hooks.as_posix()}", *args],
                              cwd=repo, capture_output=True, check=True)
    git("init", "--quiet")
    path = repo / "Task.cs"
    path.write_text("class Before {}\n", encoding="utf-8")
    git("add", "Task.cs")
    git("-c", "user.name=IRO Test", "-c", "user.email=iro-test@example.invalid", "commit", "--quiet", "-m", "first")
    path.write_text("class After {}\n", encoding="utf-8")
    git("add", "Task.cs")
    git("-c", "user.name=IRO Test", "-c", "user.email=iro-test@example.invalid", "commit", "--quiet", "-m", "second")
    reader = GitReader(repo_dir=repo, audit_logger=Mock())
    assert "class After" in reader.get_diff("HEAD~1", "HEAD")
    assert "second" in reader.show_commit("HEAD")
