from pathlib import Path

from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.knowledge.schema_scanner import SchemaScanner, SchemaScanResult, TableMetadata, ColumnMetadata
from iro_agent.knowledge.source_scanner import collect_source_evidence
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.store import ProjectKnowledgeStore


def test_static_collection_namespaces_same_entities_and_same_tables(project_config, monkeypatch):
    for source in project_config.sources.code:
        root = Path(source.path)
        (root / "TaskController.java").write_text("public class TaskController { public void dispatch() {} }", encoding="utf-8")
        (root / "application.properties").write_text("service.port=8080\n", encoding="utf-8")

    def scan(scanner):
        name = scanner.db_cfg.database
        return SchemaScanResult(database_name=name, connected=True, tables=[TableMetadata(
            table_name="task", columns=[ColumnMetadata(name=name + "_status", data_type="text")])])
    monkeypatch.setattr(SchemaScanner, "scan", scan)
    tree, schema, code, items, rules, statuses = collect_source_evidence(project_config)
    assert tree.top_level_modules == ["code_a", "code_b"]
    assert {t.source_id for t in schema.tables} == {"db_a", "db_b"}
    graph_ids = [node["entity_id"] for node in code.code_graph["entities"]]
    assert len(set(graph_ids)) == len(graph_ids)
    assert any(i.startswith("code_a::") for i in graph_ids)
    assert any(i.startswith("code_b::") for i in graph_ids)
    assert {item.source_id for item in items} == {"code_a", "code_b"}
    tables = KnowledgeSynthesizer(config=project_config)._stage_4_database_state_learning(schema, code, None)
    assert {(t.source_id, tuple(t.important_fields)) for t in tables} == {("db_a", ("db_a_status",)), ("db_b", ("db_b_status",))}
    assert all(s["status"] == "OK" for s in statuses)


def test_bootstrap_scans_all_code_sources_and_invalidates_stale_blueprint(project_config, monkeypatch):
    project_config.sources.databases = []
    for source in project_config.sources.code:
        (Path(source.path) / "TaskController.java").write_text("public class TaskController { public void dispatch() {} }", encoding="utf-8")
    bootstrapper = ProjectKnowledgeBootstrapper(project_config)
    blueprint = bootstrapper.run_bootstrap(static_only=True)
    assert {s["source_id"] for s in blueprint.data_sources} >= {"code_a", "code_b"}
    assert blueprint.bootstrap_stats["files_deep_read"] >= 2
    assert blueprint.bootstrap_stats["glm_calls"] == 0
    assert bootstrapper.store.load_blueprint() is not None
    project_config.sources.code.pop()
    assert bootstrapper.store.load_blueprint() is None
    reloaded = ProjectKnowledgeStore(base_dir=Path(project_config.project_root), config=project_config)
    assert reloaded.load_blueprint() is None
    refreshed = bootstrapper.run_bootstrap(static_only=True)
    assert refreshed.metadata["setup_fingerprint"] == project_config.setup_fingerprint()
    assert all(s["source_id"] != "code_b" for s in refreshed.data_sources)


def test_bootstrap_database_failure_does_not_erase_other_schemas(project_config, monkeypatch):
    def scan(scanner):
        if scanner.db_cfg.database == "db_b":
            return SchemaScanResult(connected=False, error="offline source-secret-db_b")
        return SchemaScanResult(connected=True, tables=[TableMetadata(table_name="task")])
    monkeypatch.setattr(SchemaScanner, "scan", scan)
    _, schema, _, _, _, statuses = collect_source_evidence(project_config)
    assert not schema.connected
    assert len(schema.tables) == 1
    assert schema.tables[0].source_id == "db_a"
    assert schema.source_status == {"db_a": "OK", "db_b": "UNAVAILABLE"}
    assert "source-secret-db_b" not in str(statuses)
