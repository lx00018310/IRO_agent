import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.investigation.models import Hypothesis, HypothesisStatus, DecisionAction
from iro_agent.llm.glm_client import GlmClient


def test_planner_has_no_tools():
    """断言 Planner 调用模型时绝不传入 tools，模型没有直接执行工具的权限 (tools == None / [])"""
    mock_glm = MagicMock(spec=GlmClient)
    # 返回合法的规划器决策 JSON
    mock_glm.complete_structured.return_value = """{
        "thought": "检查日志确认任务调度情况",
        "decision": "EXECUTE_TOOL",
        "tool_name": "log_search",
        "tool_arguments": {"keyword": "dispatch"},
        "target_hypothesis": "H1",
        "reason": "采集 dispatch 日志"
    }"""

    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="调度未触发", status=HypothesisStatus.UNRESOLVED)

    decision = planner.plan_next_step(
        symptom="月台无车",
        hypotheses=[h1],
    )

    # 1. 验证必须调用纯结构化接口 complete_structured
    assert mock_glm.complete_structured.called
    call_kwargs = mock_glm.complete_structured.call_args.kwargs
    call_args = mock_glm.complete_structured.call_args.args

    # 2. 关键硬断言：调用模型时绝对不能传递 tools 参数，或者 tools 必须为 None / []
    tools_val = call_kwargs.get("tools") if "tools" in call_kwargs else (call_args[2] if len(call_args) > 2 else None)
    assert tools_val is None or tools_val == []

    # 3. 规划器返回合法的单步决策
    assert decision.decision == DecisionAction.EXECUTE_TOOL
    assert decision.tool_name == "log_search"
