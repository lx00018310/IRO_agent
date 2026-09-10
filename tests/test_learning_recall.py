import tempfile
from pathlib import Path
from iro_agent.memory.learning_store import LearningMemoryStore


def test_learning_recall_ranking_and_usage():
    """测试学习规则的前置召回、相关度打分与命中计数"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_recall.db"
        store = LearningMemoryStore(db_path=str(db_file))

        # 录入两条不同领域的学习规则
        rule_cfg_id = store.save_rule({
            "project": "TASK-013",
            "rule_type": "configuration_rule",
            "topic": "configuration_lookup",
            "rule_text": "查询配置时必须遍历配置目录中所有配置文件，不能仅依赖 grep。",
            "reason": "历史排查遗漏了 ordersys-settings.json",
        })

        rule_table_id = store.save_rule({
            "project": "TASK-013",
            "rule_type": "source_of_truth_correction",
            "topic": "source_of_truth",
            "rule_text": "查询叫料状态时必须以 ordersys_dock_task 为准，严禁以 callback_receipt 为准。",
            "reason": "回执表存在网络异步延迟",
        })

        # 1. 模拟配置查询提问：“叫料轮询时间配置在哪？”
        recalled_cfg = store.recall_rules("叫料轮询时间配置在哪？", project="TASK-013")
        assert len(recalled_cfg) > 0
        assert recalled_cfg[0]["rule_id"] == rule_cfg_id
        assert "遍历配置目录" in recalled_cfg[0]["rule_text"]

        # 验证 use_count 自增
        rules = store.list_rules()
        cfg_rule = next(r for r in rules if r["rule_id"] == rule_cfg_id)
        assert cfg_rule["use_count"] == 1
        assert cfg_rule["last_used_at"] is not None

        # 2. 模拟业务状态提问：“当前叫料托盘状态查哪张表？”
        recalled_tbl = store.recall_rules("当前叫料托盘状态查哪张表？", project="TASK-013")
        assert len(recalled_tbl) > 0
        assert recalled_tbl[0]["rule_id"] == rule_table_id

        # 3. 模拟纯无关提问
        empty_recall = store.recall_rules("今天食堂中午吃什么？", project="TASK-013")
        assert len(empty_recall) == 0
