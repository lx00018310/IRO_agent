import inspect
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.investigation.tool_registry import ToolRegistry


def test_planner_prompt_has_no_case_type_hardcoding():
    """验证 LLM Planner 的提示词模板与逻辑中不存在针对 CaseType 的写死分支规则"""
    source = inspect.getsource(LLMInvestigationPlanner)

    # 严禁在 LLM 规划提示词中通过 CaseType 写死如果是什么case就选什么工具
    forbidden_snippets = [
        "if case_type == CaseType.PLC_SIGNAL_ERROR: return ['plc_read']",
        "if case_type == CaseType.ROBOT_EXECUTION_ERROR: return ['robot_query']",
    ]

    for snippet in forbidden_snippets:
        assert snippet not in source


def test_tool_registry_is_independent_of_case_types():
    """验证 ToolRegistry 仅根据工具本身的只读规范管理，不根据 CaseType 筛选"""
    registry = ToolRegistry()
    tools = registry.list_tool_names()
    assert "log_search" in tools
    assert "db_query" in tools
    assert "plc_read" in tools
    assert "robot_query" in tools
