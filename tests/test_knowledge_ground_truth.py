import json
import tempfile
from pathlib import Path
from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.knowledge.lookup import ProjectLookupEngine
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.config import get_config


def test_ground_truth_accuracy():
    """自动化评测 Ground-Truth 数据集中的事实源准确率与防混淆防线"""
    gt_file = Path(__file__).parent / "project_knowledge_ground_truth.json"
    with open(gt_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    # 初始化本地临时环境进行流水线 Bootstrapping
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # 写入 TASK-013 模拟结构
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
            encoding="utf-8",
        )

        cfg = get_config()
        orig_root = cfg.project_root
        orig_name = cfg.project_name
        try:
            cfg.project_root = str(root)
            cfg.project_name = "TASK-013"

            bootstrapper = ProjectKnowledgeBootstrapper(config=cfg)
            bp = bootstrapper.run_bootstrap(refresh=True, use_llm=False)

            store = ProjectKnowledgeStore(base_dir=root)
            engine = ProjectLookupEngine(store=store)

            for case in cases:
                q = case["question"]
                expected_src = case["expected_primary_source"]
                forbidden_srcs = case["forbidden_primary_sources"]

                res = engine.lookup(q)
                assert res["status"] == "SUCCESS", f"查询失败: {q}"

                # 验证权威源命中
                found_canonical = False
                for c in res["concepts"]:
                    cs = c.get("canonical_source", {})
                    if isinstance(cs, dict) and cs.get("table") == expected_src:
                        found_canonical = True
                for r in res["rules"]:
                    if expected_src in r.get("canonical_source", ""):
                        found_canonical = True

                assert found_canonical, f"问题 '{q}' 未能正确识别权威源 '{expected_src}', 实际返回: {res}"

                # 验证禁止误用的源
                for forbidden in forbidden_srcs:
                    for c in res["concepts"]:
                        cs = c.get("canonical_source", {})
                        if isinstance(cs, dict):
                            assert cs.get("table") != forbidden, f"安全防线失效: '{forbidden}' 被错误用作主源"
                    # 检查警告中是否已明确提醒
                    warning_texts = " ".join(res["warnings"])
                    assert forbidden in warning_texts, f"告警缺失: 未在 warnings 中发现对 '{forbidden}' 的防踩坑提示"
        finally:
            cfg.project_root = orig_root
            cfg.project_name = orig_name

