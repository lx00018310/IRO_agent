import pytest
from unittest.mock import MagicMock, patch
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.tool_registry import ToolRegistry
from iro_agent.readers.log_reader import LogReader


def test_log_search_contract_accepts_limit_argument():
    """验证 ToolRegistry 中的 log_search 契约参数 'limit' 能正确映射到底层 LogReader 的 'max_results'"""
    registry = ToolRegistry()
    spec = registry.get_tool("log_search")
    assert spec is not None
    assert "keyword" in spec.parameters_schema
    assert "limit" in spec.parameters_schema

    harness = InvestigationHarness(planner_mode="deterministic")
    adapter = harness.tool_handlers.get("log_search")
    assert adapter is not None

    with patch.object(LogReader, "search_logs", return_value=[{"msg": "log_entry"}]) as mock_search:
        # 1. 严格使用 ToolRegistry 规定的契约参数 'keyword' 与 'limit'
        res = adapter(keyword="timeout", limit=30)
        assert res == [{"msg": "log_entry"}]
        mock_search.assert_called_once_with(keyword="timeout", max_results=30)

    with patch.object(LogReader, "search_logs", return_value=[{"msg": "log_entry_2"}]) as mock_search2:
        # 2. 兼容使用底层参数 'max_results'
        res2 = adapter(keyword="error", max_results=50)
        assert res2 == [{"msg": "log_entry_2"}]
        mock_search2.assert_called_once_with(keyword="error", max_results=50)

    with patch.object(LogReader, "search_logs", return_value=[{"msg": "log_entry_3"}]) as mock_search3:
        # 3. 传入模型可能携带的额外冗余 kwargs，不出现 TypeError: unexpected keyword argument
        res3 = adapter(keyword="exception", limit=15, time_range="last_1h", trace_id="123")
        assert res3 == [{"msg": "log_entry_3"}]
        mock_search3.assert_called_once()
