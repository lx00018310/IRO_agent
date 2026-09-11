import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.investigation.models import Hypothesis, HypothesisStatus
from iro_agent.llm.glm_client import GlmClient, SYSTEM_PROMPT as GENERAL_LEGACY_PROMPT


def test_planner_does_not_receive_general_system_prompt():
    """断言 Planner 绝不接收全局旧 SYSTEM_PROMPT，彻底隔离通用 Agent 提示词"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.complete_structured.return_value = """{
        "thought": "证据已收敛",
        "decision": "CONVERGE",
        "reason": "已明确根因"
    }"""

    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="任务停滞", status=HypothesisStatus.UNRESOLVED)

    planner.plan_next_step(
        symptom="小车未下发任务",
        hypotheses=[h1],
    )

    assert mock_glm.complete_structured.called
    call_kwargs = mock_glm.complete_structured.call_args.kwargs
    system_prompt = call_kwargs.get("system_prompt", "")
    prompt = call_kwargs.get("prompt", "")

    # 关键断言：绝不能包含旧全局 SYSTEM_PROMPT 的特有语句
    assert "你是工业现场只读智能诊断助手 IRO_agent" not in system_prompt
    assert "你是工业现场只读智能诊断助手 IRO_agent" not in prompt
    assert "【核心原则：极端精简，拒绝任何废话，直切要害】" not in system_prompt
    assert "【核心原则：极端精简，拒绝任何废话，直切要害】" not in prompt
