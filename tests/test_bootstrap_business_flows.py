import tempfile
from pathlib import Path
from iro_agent.knowledge.models import BusinessFlow, ProjectBlueprint, ProjectMetadata
from iro_agent.knowledge.business_flows import BusinessFlowLearner
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.lookup import ProjectLookupEngine


def test_business_flow_learning_and_lookup():
    """测试端到端核心业务流的学习建模与自然语言检索"""
    flows = BusinessFlowLearner.discover_flows(
        apis=[],
        tables=[],
        code_graph_dict=None,
        project_name="TASK-013",
    )

    assert len(flows) >= 2
    call_flow = next(f for f in flows if "叫料" in f.name)
    assert call_flow.controller == "DockTaskController"
    assert "ordersys_dock_task" in call_flow.tables
    assert "materialCallPollIntervalSeconds" in call_flow.configs
    assert "WMS系统" in call_flow.external_systems
    assert call_flow.source_of_truth == "ordersys_dock_task"

    # 测试存储与通过 ProjectLookupEngine 的 flow_lookup 检索
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = ProjectKnowledgeStore(base_dir=root)
        bp = ProjectBlueprint(
            project=ProjectMetadata(
                project_id="TASK-013",
                project_name="TASK-013",
                generated_at="2026-09-10",
                source_root=str(root),
            ),
            business_flows=flows,
        )
        store.save_blueprint(bp)

        engine = ProjectLookupEngine(store=store)
        res = engine.flow_lookup("物料叫料与装车轮询")
        assert res["status"] == "SUCCESS"
        assert len(res["flows"]) > 0
        hit = res["flows"][0]
        assert "叫料" in hit["name"]
        assert hit["controller"] == "DockTaskController"
