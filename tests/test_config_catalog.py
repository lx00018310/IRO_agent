import json
import tempfile
from pathlib import Path
from iro_agent.knowledge.config_catalog import ConfigCatalogScanner, search_config_catalog


def test_config_catalog_scanner_multi_format_and_redaction():
    """测试 ConfigCatalog 对 JSON/YAML/Properties 多格式配置的全目录遍历与敏感词脱敏"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # 1. 模拟 ordersys-settings.json (含轮询时间与敏感密码)
        cfg_dir = root / "deployment_control" / "native"
        cfg_dir.mkdir(parents=True)
        json_file = cfg_dir / "ordersys-settings.json"
        json_file.write_text(
            json.dumps({
                "materialCallPollIntervalSeconds": 5,
                "plcAddress": "192.168.1.100",
                "plcPort": 502,
                "db_password": "super_secret_password_12345",
                "api_key": "sk-proj-abc1234567890abcdef",
            }),
            encoding="utf-8"
        )

        # 2. 模拟 application.yml
        yml_file = root / "backend" / "application.yml"
        yml_file.parent.mkdir(parents=True)
        yml_file.write_text(
            """
server:
  port: 8080
app:
  callbackTimeoutSeconds: 30
  secret_key: 'top_secret_token_abcdefg'
""",
            encoding="utf-8"
        )

        # 3. 模拟 system.properties
        prop_file = root / "config" / "system.properties"
        prop_file.parent.mkdir(parents=True)
        prop_file.write_text(
            """
# 轮询参数
worker.poll.interval.ms=1000
db.password=my_prod_password_9999
""",
            encoding="utf-8"
        )

        # 扫描
        scanner = ConfigCatalogScanner(root)
        catalog, priority_rules = scanner.scan()

        assert len(catalog) >= 6
        assert len(priority_rules) >= 1

        # 验证敏感信息绝不持久化明文
        for item in catalog:
            raw_val = str(item.default_value)
            assert "super_secret_password_12345" not in raw_val
            assert "sk-proj-abc1234567890abcdef" not in raw_val
            assert "top_secret_token_abcdefg" not in raw_val
            assert "my_prod_password_9999" not in raw_val

        # 验证 ordersys-settings.json 关键字段解析与语义推导
        poll_item = next((i for i in catalog if i.key == "materialCallPollIntervalSeconds"), None)
        assert poll_item is not None
        assert poll_item.unit == "秒 (s)"
        assert "轮询" in poll_item.business_meaning
        assert "ordersys-settings.json" in poll_item.relative_path

        # 检索测试
        hits = search_config_catalog(catalog, "叫料轮询时间配置")
        assert len(hits) > 0
        assert hits[0]["key"] == "materialCallPollIntervalSeconds"
        assert "ordersys-settings.json" in hits[0]["relative_path"]
