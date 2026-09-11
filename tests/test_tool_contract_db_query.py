import pytest
from unittest.mock import MagicMock, patch
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.tool_registry import ToolRegistry
from iro_agent.readers.db_reader import DatabaseReader


def test_db_query_contract_accepts_sql_argument():
    """验证 ToolRegistry 中的 db_query 契约参数 'sql' 能直接被 runtime adapter 接收执行，不报入参错误"""
    registry = ToolRegistry()
    spec = registry.get_tool("db_query")
    assert spec is not None
    assert "sql" in spec.parameters_schema

    harness = InvestigationHarness(planner_mode="deterministic")
    adapter = harness.tool_handlers.get("db_query")
    assert adapter is not None

    with patch.object(DatabaseReader, "execute_query", return_value=[{"id": 1}]) as mock_exec:
        # 1. 严格使用 ToolRegistry 规定的契约参数 'sql'
        res = adapter(sql="SELECT * FROM sys_task WHERE id=1")
        assert res == [{"id": 1}]
        mock_exec.assert_called_once_with(query="SELECT * FROM sys_task WHERE id=1", max_rows=100)

    with patch.object(DatabaseReader, "execute_query", return_value=[{"id": 2}]) as mock_exec2:
        # 2. 兼容使用底层参数 'query'
        res2 = adapter(query="SELECT 1")
        assert res2 == [{"id": 2}]
        mock_exec2.assert_called_once_with(query="SELECT 1", max_rows=100)

    with patch.object(DatabaseReader, "execute_query", return_value=[{"id": 3}]) as mock_exec3:
        # 3. 传入模型可能携带的额外冗余 kwargs，不出现 TypeError: unexpected keyword argument
        res3 = adapter(sql="SELECT * FROM sys_device", extra_unrelated_param="test", limit=10)
        assert res3 == [{"id": 3}]
        mock_exec3.assert_called_once()
