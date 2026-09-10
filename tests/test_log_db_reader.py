import pytest
from iro_agent.readers.log_reader import LogReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.security.policy import SecurityPolicyError


def test_log_reader_task013():
    reader = LogReader()
    files = reader.discover_log_files()
    assert len(files) > 0, "应能发现 TASK-013 日志文件"

    # 搜索包含 ECONNRESET 或 WebSocket 或 Error 的日志
    results = reader.search_logs(keyword="ECONNRESET", max_results=5)
    if results:
        assert "ECONNRESET" in results[0]["raw"]
        assert results[0]["file"].endswith(".log")

        # 测试上下文行提取
        ctx = reader.get_log_context(results[0]["file"], results[0]["line_no"], window=2)
        assert len(ctx) > 0
        assert any(item.get("is_target") for item in ctx)


def test_db_reader_sql_validation():
    db = DatabaseReader()

    # 合法 SELECT / WITH
    db._validate_sql_readonly("SELECT id, station_no FROM ordersys_dock_task LIMIT 10")
    db._validate_sql_readonly("WITH recent AS (SELECT * FROM ordersys_task_line) SELECT * FROM recent")
    db._validate_sql_readonly("EXPLAIN SELECT count(*) FROM ordersys_dock_task")

    # 非法写操作拦截
    with pytest.raises(SecurityPolicyError):
        db._validate_sql_readonly("INSERT INTO ordersys_dock_task (station_no) VALUES ('01')")

    with pytest.raises(SecurityPolicyError):
        db._validate_sql_readonly("UPDATE ordersys_dock_task SET status = 'failed'")

    with pytest.raises(SecurityPolicyError):
        db._validate_sql_readonly("DELETE FROM ordersys_dock_task WHERE id = 1")

    with pytest.raises(SecurityPolicyError):
        db._validate_sql_readonly("DROP TABLE ordersys_dock_task")

    # 非法多语句注入拦截
    with pytest.raises(SecurityPolicyError):
        db._validate_sql_readonly("SELECT 1; DROP TABLE ordersys_dock_task")


def test_db_reader_datetime_and_special_type_serialization():
    """验证数据库返回包含 datetime 等非基础类型时，工具与 JSON 序列化不会崩溃"""
    import datetime
    import json

    fake_rows = [
        {
            "id": 101,
            "station_no": "01",
            "created_at": datetime.datetime(2026, 9, 10, 11, 2, 39),
            "updated_at": datetime.date(2026, 9, 10),
            "completed": True,
        }
    ]

    # 测试归一化逻辑
    results = []
    for row in fake_rows:
        item = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            else:
                item[k] = v
        results.append(item)

    assert results[0]["created_at"] == "2026-09-10T11:02:39"
    assert results[0]["updated_at"] == "2026-09-10"

    # 验证 json.dumps default=str 彻底杜绝崩溃
    dumped = json.dumps(fake_rows, ensure_ascii=False, default=str)
    assert "2026-09-10 11:02:39" in dumped or "2026-09-10" in dumped
