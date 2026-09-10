import json
import tempfile
from pathlib import Path
from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.config import get_config


def test_deep_bootstrap_ten_stages_and_rich_blueprint():
    """测试 10 阶段深度项目自举全景蓝图的生成、校验与持久化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # 1. 构造工程目录与文件
        (root / "backend").mkdir()
        (root / "backend" / "models.py").write_text(
            """
class DockTask:
    station_no = None
    current_pallet_slot = None
    class Meta:
        db_table = "ordersys_dock_task"

class DispatchReceipt:
    received_at = None
    class Meta:
        db_table = "ordersys_dispatch_callback_receipt"
""",
            encoding="utf-8"
        )
        (root / "start_server.bat").write_text("python backend/main.py", encoding="utf-8")
        (root / "deploy.sh").write_text("echo deploying", encoding="utf-8")

        # 2. 构造配置文件
        (root / "deployment_control").mkdir()
        (root / "deployment_control" / "ordersys-settings.json").write_text(
            json.dumps({
                "materialCallPollIntervalSeconds": 10,
                "plcAddress": "10.0.0.1",
            }),
            encoding="utf-8"
        )

        cfg = get_config()
        orig_root = cfg.project_root
        orig_name = cfg.project_name
        try:
            cfg.project_root = str(root)
            cfg.project_name = "TASK-013"

            bootstrapper = ProjectKnowledgeBootstrapper(config=cfg)
            bp = bootstrapper.run_bootstrap(refresh=True, use_llm=False)

            # 验证全景图深度
            assert bp.project_overview is not None
            assert len(bp.project_overview.modules) >= 2
            assert "start_server.bat" in bp.project_overview.startup_scripts
            assert "deploy.sh" in bp.project_overview.deployment_scripts

            # 验证配置目录
            assert len(bp.config_catalog) >= 2
            assert any(c.key == "materialCallPollIntervalSeconds" for c in bp.config_catalog)

            # 验证数据表语义与事实源权威规则
            tbl_names = {t.table_name for t in bp.database_tables}
            assert "ordersys_dock_task" in tbl_names
            assert "ordersys_dispatch_callback_receipt" in tbl_names

            dock_tbl = next(t for t in bp.database_tables if t.table_name == "ordersys_dock_task")
            assert dock_tbl.table_type in ("current_state", "master")

            # 验证业务流与外部系统
            assert len(bp.business_flows) >= 1
            assert len(bp.external_systems) >= 1

            # 验证持久化与可读 Markdown
            store = ProjectKnowledgeStore(base_dir=root)
            assert store.exists()
            assert store.markdown_path.exists()

            md_content = store.markdown_path.read_text(encoding="utf-8")
            assert "核心事实源规则" in md_content
            assert "配置全目录认知" in md_content
            assert "端到端核心业务链路" in md_content
            assert "外部依赖与协同系统" in md_content
        finally:
            cfg.project_root = orig_root
            cfg.project_name = orig_name
