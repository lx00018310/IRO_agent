import tempfile
import json
from pathlib import Path
from iro_agent.knowledge.models import (
    ProjectBlueprint,
    ProjectMetadata,
    BusinessConcept,
    SourceOfTruthRule,
    TableKnowledge,
)
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.lookup import ProjectLookupEngine


def test_knowledge_store_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProjectKnowledgeStore(base_dir=Path(tmpdir))
        assert not store.exists()
        assert store.load_blueprint() is None

        bp = ProjectBlueprint(
            project=ProjectMetadata(
                project_id="TASK-013",
                project_name="武汉自动上车显示屏",
                generated_at="2026-09-10 12:00:00",
                source_root=tmpdir,
            ),
            business_concepts=[
                BusinessConcept(
                    concept_id="current_pallet",
                    name="当前托盘",
                    aliases=["最新一托", "当前一托"],
                    description="月台当前托盘物料状态",
                    canonical_source={"type": "database", "table": "ordersys_dock_task", "field": "current_pallet_slot"},
                    do_not_use_as_primary=["ordersys_dispatch_callback_receipt"],
                )
            ],
            source_of_truth_rules=[
                SourceOfTruthRule(
                    fact="当前月台正在处理哪一托",
                    canonical_source="ordersys_dock_task.current_pallet_slot",
                    invalid_primary_sources=["ordersys_dispatch_callback_receipt"],
                    reason="callback_receipt 仅为外部调度系统的历史回调到货回执，不代表月台实时当前状态",
                )
            ],
            database_tables=[
                TableKnowledge(
                    table_name="ordersys_dock_task",
                    business_role="月台主调度任务表，承载当前托盘实时状态",
                    table_type="current_state",
                    status_fields=["status"],
                    time_fields=["updated_at", "created_at"],
                ),
                TableKnowledge(
                    table_name="ordersys_dispatch_callback_receipt",
                    business_role="第三方调度实到回执日志表",
                    table_type="callback",
                    not_for=["当前实时月台托盘状态查询"],
                ),
            ],
        )

        store.save_blueprint(bp)
        assert store.exists()
        assert (Path(tmpdir) / ".iro_agent" / "project_blueprint.json").exists()
        assert (Path(tmpdir) / ".iro_agent" / "project_blueprint.md").exists()

        loaded = store.load_blueprint(reload=True)
        assert loaded is not None
        assert loaded.project.project_id == "TASK-013"
        assert len(loaded.business_concepts) == 1
        assert len(loaded.source_of_truth_rules) == 1

        # 测试 lookup 引擎
        engine = ProjectLookupEngine(store=store)
        res = engine.lookup("查询最新一托的调度信息")
        assert res["status"] == "SUCCESS"
        assert len(res["concepts"]) == 1
        assert res["concepts"][0]["concept"] == "当前托盘"
        assert len(res["rules"]) == 1
        assert "ordersys_dock_task" in res["rules"][0]["canonical_source"]
        assert len(res["warnings"]) >= 1
        assert "ordersys_dispatch_callback_receipt" in res["warnings"][0]


def test_knowledge_override():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ProjectKnowledgeStore(base_dir=Path(tmpdir))
        bp = ProjectBlueprint(
            project=ProjectMetadata(
                project_id="TASK-013",
                project_name="测试工程",
                generated_at="2026-09-10 12:00:00",
                source_root=tmpdir,
            ),
            source_of_truth_rules=[
                SourceOfTruthRule(
                    fact="测试事实",
                    canonical_source="table_a",
                )
            ],
        )
        store.save_blueprint(bp)

        # 写入 override 文件
        override_file = Path(tmpdir) / ".iro_agent" / "project_knowledge_override.json"
        override_data = {
            "source_of_truth_rules": [
                {
                    "fact": "测试事实",
                    "canonical_source": "table_override_winner",
                    "secondary_sources": [],
                    "invalid_primary_sources": ["table_a"],
                    "reason": "人工权威修正",
                    "confidence": "confirmed",
                    "sources": ["manual_override"],
                }
            ]
        }
        with open(override_file, "w", encoding="utf-8") as f:
            json.dump(override_data, f)

        loaded = store.load_blueprint(reload=True)
        assert loaded.source_of_truth_rules[0].canonical_source == "table_override_winner"
