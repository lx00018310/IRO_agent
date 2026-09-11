import pytest
from unittest.mock import patch, MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.tool_registry import ToolRegistry


def test_all_agentic_tools_have_runtime_adapters():
    """验证 ToolRegistry 中的所有核心排查工具在 Harness 中均有注册可执行的 Adapter"""
    harness = InvestigationHarness(planner_mode="deterministic")
    registry = harness.tool_registry
    tool_names = registry.list_tool_names()

    for name in tool_names:
        assert name in harness.tool_handlers, f"工具 '{name}' 在 ToolRegistry 中已定义，但在 harness.tool_handlers 中缺失"


def test_agentic_tools_execute_with_minimal_contract_args_without_typeerror():
    """验证 ToolRegistry 中的每个工具，使用符合其 schema 的最小合法参数调用 adapter 时，绝不发生 TypeError: unexpected keyword argument"""
    harness = InvestigationHarness(planner_mode="deterministic")
    registry = harness.tool_registry

    # 为每个工具准备符合 ToolRegistry parameters_schema 的最小合法入参
    minimal_args = {
        "log_search": {"keyword": "test_error", "limit": 10},
        "db_query": {"sql": "SELECT 1"},
        "db_describe": {"table_name": "sys_task"},
        "config_lookup": {"query": "timeout"},
        "project_lookup": {"query": "robot"},
        "code_search": {"query": "execute_task"},
        "version_current": {},
        "web_fetch": {"url": "http://127.0.0.1:8080/health"},
        "plc_read": {"address": "DB1.DBD0"},
        "robot_query": {"query_type": "status"},
    }

    with patch("iro_agent.readers.log_reader.LogReader.search_logs", return_value=[]), \
         patch("iro_agent.readers.db_reader.DatabaseReader.execute_query", return_value=[]), \
         patch("iro_agent.readers.db_reader.DatabaseReader.describe_table", return_value=[]), \
         patch("iro_agent.knowledge.lookup.ProjectLookupEngine.config_lookup", return_value={"status": "NO_MATCH"}), \
         patch("iro_agent.knowledge.lookup.ProjectLookupEngine.lookup", return_value={"status": "NOT_BOOTSTRAPPED"}), \
         patch("iro_agent.readers.code_reader.CodeReader.search_code", return_value=[]), \
         patch("iro_agent.readers.web_reader.WebReader.fetch_page", return_value={"status": 200, "content": "ok"}):

        for tool_name, args in minimal_args.items():
            handler = harness.tool_handlers.get(tool_name)
            assert handler is not None, f"Handler for {tool_name} not found"

            # 1. 最小合法参数执行：严禁拋出 TypeError (尤其是 unexpected keyword argument)
            try:
                res = handler(**args)
                assert res is not None
            except TypeError as te:
                pytest.fail(f"工具 {tool_name} 契约违背！以参数 {args} 执行抛出 TypeError: {te}")

            # 2. 携带冗余参数执行：严禁因模型幻觉附加参数导致 TypeError
            args_with_extra = dict(args)
            args_with_extra["model_hallucinated_extra_param"] = "redundant_val"
            try:
                res_extra = handler(**args_with_extra)
                assert res_extra is not None
            except TypeError as te:
                pytest.fail(f"工具 {tool_name} Adapter 未能吸收冗余参数！抛出 TypeError: {te}")
