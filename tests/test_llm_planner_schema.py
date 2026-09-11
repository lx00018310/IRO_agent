import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.investigation.planner_validator import PlannerValidator


def test_planner_decision_schema_parsing():
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = """
```json
{
  "thought": "目前发现调度任务停留在 WAITING，需要检查数据库中具体字段状态",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "db_query",
  "tool_arguments": {"sql": "SELECT id, status, execute_status FROM ordersys_dock_task WHERE id = 1001"},
  "reason": "验证任务是否确实卡在中间状态"
}
```
"""
    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="任务状态机卡在中间状态")

    decision = planner.plan_next_step(
        symptom="任务停留在 WAITING 不动",
        hypotheses=[h1],
    )

    assert decision.decision == DecisionAction.EXECUTE_TOOL
    assert decision.target_hypothesis == "H1"
    assert decision.tool_name == "db_query"
    assert "SELECT" in decision.tool_arguments.get("sql", "")
    assert decision.error is None


def test_planner_converge_decision():
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = """
{
  "thought": "日志与数据库证据已完全闭环，明确为 PLC 边界端口断开引发超时",
  "decision": "CONVERGE",
  "reason": "已找到确定性根因"
}
"""
    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="PLC 端口断开", status=HypothesisStatus.CONFIRMED)

    decision = planner.plan_next_step(symptom="PLC 通信超时", hypotheses=[h1])

    assert decision.decision == DecisionAction.CONVERGE
    assert decision.error is None


def test_planner_physical_escalation_decision():
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = """
{
  "thought": "数字系统服务与通信均显示正常，判断可能为现场光电传感器被异物遮挡",
  "decision": "ESCALATE_PHYSICAL",
  "reason": "建议现场电气人员检查光电传感器与安全门闭锁"
}
"""
    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    decision = planner.plan_next_step(symptom="料箱未到位但无系统报警", hypotheses=[])

    assert decision.decision == DecisionAction.ESCALATE_PHYSICAL
    assert decision.error is None
