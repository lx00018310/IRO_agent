import json
import tempfile
from pathlib import Path
from iro_agent.memory.learning_store import LearningMemoryStore
from iro_agent.memory.correction_detector import CorrectionDetector
from iro_agent.router.intent_router import IntentRouter, QueryIntent
from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.knowledge.lookup import ProjectLookupEngine
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.config import get_config


def test_task013_case1_and_case5_restart_safe_configuration_memory():
    """TASK-013 Case 1 & Case 5: 配置纠错规则持久化、跨重启依然生效并导引检索到 ordersys-settings.json"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_file = root / "memory.db"

        # 1. 用户下发纠错指令并由 CorrectionDetector 识别
        user_correction = "记住：查询配置应该遍历配置目录中的所有配置文件，不能只用 grep。"
        detected = CorrectionDetector.detect(user_correction)
        assert detected is not None
        assert detected["rule_type"] == "configuration_rule"

        # 模拟第一个运行实例保存规则
        store1 = LearningMemoryStore(db_path=str(db_file))
        rule_id = store1.save_rule({
            "project": "TASK-013",
            "rule_type": detected["rule_type"],
            "topic": detected["topic"],
            "rule_text": detected["rule_text"],
            "reason": "历史排查曾因 grep 遗漏了 ordersys-settings.json",
            "confidence": "confirmed",
        })
        honesty_reply = CorrectionDetector.format_honesty_response(rule_id=rule_id, rule_text=detected["rule_text"])
        assert "已持久化记住该原则" in honesty_reply

        # 2. 模拟进程退出与重启 (关闭 store1，创建全新的 store2 实例连接同一个数据库文件)
        del store1
        store2 = LearningMemoryStore(db_path=str(db_file))

        # 3. 再次询问：“叫料轮询时间配置在哪？”
        query = "叫料轮询时间配置在哪？"
        intent_info = IntentRouter.route(query)
        assert intent_info["intent"] == QueryIntent.CONFIGURATION

        # 4. 执行 learning_recall 召回学习记忆
        recalled = store2.recall_rules(query, project="TASK-013")
        assert len(recalled) > 0
        assert recalled[0]["rule_id"] == rule_id
        assert "遍历配置目录" in recalled[0]["rule_text"]

        # 5. 模拟在项目认知库中通过 ConfigCatalog 进行 config_lookup
        deploy_dir = root / "deployment_control" / "native"
        deploy_dir.mkdir(parents=True)
        (deploy_dir / "ordersys-settings.json").write_text(
            json.dumps({"materialCallPollIntervalSeconds": 5, "description": "物料叫料轮询周期"}),
            encoding="utf-8"
        )
        (root / "backend").mkdir()
        (root / "backend" / "models.py").write_text("class DockTask:\n    pass\n", encoding="utf-8")

        cfg = get_config()
        orig_root = cfg.project_root
        try:
            cfg.project_root = str(root)
            bootstrapper = ProjectKnowledgeBootstrapper(config=cfg)
            bp = bootstrapper.run_bootstrap(refresh=True, use_llm=False)

            p_store = ProjectKnowledgeStore(base_dir=root)
            engine = ProjectLookupEngine(store=p_store)

            lookup_res = engine.config_lookup(query)
            assert lookup_res["status"] == "SUCCESS"
            assert len(lookup_res["items"]) > 0
            best_hit = lookup_res["items"][0]
            assert best_hit["key"] == "materialCallPollIntervalSeconds"
            assert "ordersys-settings.json" in best_hit["relative_path"]
        finally:
            cfg.project_root = orig_root


def test_task013_case2_and_case3_case4_deep_bootstrap_depth():
    """TASK-013 Case 2, 3, 4: 10 阶段自举全景知识、ConfigCatalog 索引以及端到端业务流"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "backend").mkdir()
        (root / "backend" / "models.py").write_text(
            """
class DockTask:
    station_no = None
    class Meta:
        db_table = "ordersys_dock_task"

class DispatchReceipt:
    class Meta:
        db_table = "ordersys_dispatch_callback_receipt"
""",
            encoding="utf-8"
        )
        (root / "ordersys-settings.json").write_text(
            json.dumps({"materialCallPollIntervalSeconds": 8}),
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

            # Case 2: 深度知识层完备性校验
            assert bp.project_overview is not None
            assert len(bp.modules) >= 1
            assert len(bp.config_catalog) >= 1
            assert len(bp.database_tables) >= 2
            assert len(bp.business_flows) >= 1
            assert len(bp.external_systems) >= 1
            assert len(bp.source_of_truth_rules) >= 1

            # Case 3: Config Catalog 检索
            p_store = ProjectKnowledgeStore(base_dir=root)
            engine = ProjectLookupEngine(store=p_store)
            res_cfg = engine.config_lookup("materialCallPollIntervalSeconds")
            assert res_cfg["status"] == "SUCCESS"
            assert res_cfg["items"][0]["key"] == "materialCallPollIntervalSeconds"

            # Case 4: Business Flow 端到端调用链
            res_flow = engine.flow_lookup("叫料流程")
            assert res_flow["status"] == "SUCCESS"
            assert len(res_flow["flows"]) > 0
            flow = res_flow["flows"][0]
            assert "ordersys_dock_task" in flow["tables"]
            assert flow["source_of_truth"] == "ordersys_dock_task"
        finally:
            cfg.project_root = orig_root
            cfg.project_name = orig_name
