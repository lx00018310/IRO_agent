import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    Hypothesis,
)
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner


def test_planner_retry_on_invalid_json_then_succeed():
    mock_glm = MagicMock()
    # 第一次输出非合法 JSON，第二次输出合法 JSON
    mock_glm.chat_completion.side_effect = [
        "我认为应该查日志，因为之前可能报错了。（无 JSON）",
        """```json
{
  "thought": "纠正格式，输出标准决策",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "Connection reset"},
  "reason": "排查网络连接中断证据"
}
```""",
    ]

    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="网络中断假设")

    decision = planner.plan_next_step(
        symptom="网络中断",
        hypotheses=[h1],
        max_retries=1,
    )

    # 验证触发了重试 (调用了 2 次 chat_completion)
    assert mock_glm.chat_completion.call_count == 2
    assert decision.decision == DecisionAction.EXECUTE_TOOL
    assert decision.tool_name == "log_search"
    assert decision.error is None


def test_planner_retry_on_whitelist_violation_then_succeed():
    mock_glm = MagicMock()
    # 第一次输出了非法工具 shell_cmd，收到 feedback 后修正为只读 log_search
    mock_glm.chat_completion.side_effect = [
        """```json
{
  "thought": "执行系统命令查日志",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "shell_cmd",
  "tool_arguments": {"cmd": "cat /var/log/app.log"},
  "reason": "看日志"
}
```""",
        """```json
{
  "thought": "纠正为合法的只读工具 log_search",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "ERROR"},
  "reason": "看日志"
}
```""",
    ]

    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="应用服务异常")

    decision = planner.plan_next_step(
        symptom="服务不可用",
        hypotheses=[h1],
        max_retries=1,
    )

    assert mock_glm.chat_completion.call_count == 2
    assert decision.decision == DecisionAction.EXECUTE_TOOL
    assert decision.tool_name == "log_search"
    assert decision.error is None


def test_planner_safety_fallback_after_max_retries():
    mock_glm = MagicMock()
    # 持续输出非法内容
    mock_glm.chat_completion.return_value = "持续格式错误，不按规矩输出"

    planner = LLMInvestigationPlanner(glm_client=mock_glm)
    h1 = Hypothesis(hypothesis_id="H1", description="异常")

    decision = planner.plan_next_step(
        symptom="服务异常",
        hypotheses=[h1],
        max_retries=1,
    )

    # 验证不 crash，安全降级为收敛并标记错误
    assert decision.decision == DecisionAction.CONVERGE
    assert decision.error is not None
    assert "PLANNER_ERROR" in decision.error
