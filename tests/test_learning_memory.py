import tempfile
from pathlib import Path
from iro_agent.memory.learning_store import LearningMemoryStore


def test_learning_store_save_and_restart_persistence():
    """测试学习记忆规则保存及跨实例/重启持久化验证"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_learning.db"

        # 1. 模拟第一个实例执行 save_rule
        store1 = LearningMemoryStore(db_path=str(db_file))
        rule_data = {
            "project": "TASK-013",
            "rule_type": "configuration_rule",
            "topic": "configuration_lookup",
            "rule_text": "查询配置时必须遍历允许读取的配置目录及其中所有配置文件，不能仅依赖代码 grep。",
            "reason": "ordersys-settings.json 曾因只做 grep 而被漏检",
            "source_type": "user_correction",
            "confidence": "confirmed",
        }
        rule_id = store1.save_rule(rule_data)
        assert rule_id.startswith("RULE-")

        # 2. 模拟进程完全关闭后，新建全新实例连接同一个 SQLite 数据库（模拟重启）
        del store1
        store2 = LearningMemoryStore(db_path=str(db_file))

        rules = store2.list_rules(project="TASK-013")
        assert len(rules) == 1
        saved_rule = rules[0]
        assert saved_rule["rule_id"] == rule_id
        assert saved_rule["rule_type"] == "configuration_rule"
        assert saved_rule["topic"] == "configuration_lookup"
        assert "遍历允许读取的配置目录" in saved_rule["rule_text"]
        assert saved_rule["use_count"] == 0
        assert saved_rule["status"] == "active"


def test_learning_store_update_and_deactivate():
    """测试规则更新与停用机制"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_learning.db"
        store = LearningMemoryStore(db_path=str(db_file))

        rule_id = store.save_rule({
            "rule_text": "历史表不能作为实时状态判断依据",
            "topic": "table_usage",
            "rule_type": "business_semantic_correction",
        })

        # 更新规则内容
        store.save_rule({
            "rule_id": rule_id,
            "rule_text": "历史表与回执表均严禁作为实时状态判断依据",
            "topic": "table_usage",
            "rule_type": "business_semantic_correction",
        })

        rules = store.list_rules()
        assert len(rules) == 1
        assert "回执表" in rules[0]["rule_text"]

        # 停用规则
        ok = store.deactivate_rule(rule_id)
        assert ok is True
        active_rules = store.list_rules(status="active")
        assert len(active_rules) == 0
        all_rules = store.list_rules(status="inactive")
        assert len(all_rules) == 1
