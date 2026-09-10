import tempfile
from pathlib import Path
from iro_agent.knowledge.tree_scanner import TreeScanner
from iro_agent.knowledge.code_scanner import TargetedCodeScanner
from iro_agent.knowledge.schema_scanner import SchemaScanner
from iro_agent.config import DatabaseConfig


def test_tree_scanner_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # 创建伪项目结构
        (root / "backend").mkdir()
        (root / "backend" / "models.py").write_text("class TestModel:\n    pass\n", encoding="utf-8")
        (root / "node_modules").mkdir()  # 黑名单
        (root / "node_modules" / "test.js").write_text("console.log()", encoding="utf-8")
        (root / "manage.py").write_text("# django manage.py", encoding="utf-8")

        scanner = TreeScanner(root)
        res = scanner.scan()
        assert res.total_files >= 2
        assert "backend" in res.top_level_modules
        assert "node_modules" not in res.top_level_modules
        assert "Django" in res.frameworks
        assert res.primary_language == "Python"


def test_code_scanner_model_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model_file = root / "models.py"
        model_code = """
from django.db import models

class DockTask(models.Model):
    station_no = models.CharField(max_length=32)
    current_pallet_slot = models.JSONField(null=True)
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ordersys_dock_task"

class TaskStatus(models.TextChoices):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
"""
        model_file.write_text(model_code, encoding="utf-8")

        scanner = TargetedCodeScanner(root)
        res = scanner.scan()
        assert res.detected_models_count >= 1
        m = next(e for e in res.entities if e.entity_type == "model")
        assert m.name == "DockTask"
        assert m.mapped_table == "ordersys_dock_task"
        assert "station_no" in m.fields_or_constants
        assert "current_pallet_slot" in m.fields_or_constants

        e = next(e for e in res.entities if e.entity_type == "enum")
        assert e.name == "TaskStatus"
        assert "COMPLETED" in e.fields_or_constants


def test_schema_scanner_graceful_fallback():
    # 测试无效或不可连配置下的优雅降级
    bad_cfg = DatabaseConfig(host="127.0.0.1", port=59999, database="not_exist", user="none", password="none")
    scanner = SchemaScanner(db_config=bad_cfg)
    res = scanner.scan()
    assert res.connected is False
    assert res.error is not None
