import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.llm.glm_client import GlmClient


def test_planner_error_does_not_fallback_to_deterministic():
    """断言 LLM Planner 异常时立即显式中止排查，严禁静默 fallback 到确定性模式继续排查"""
    mock_glm = MagicMock(spec=GlmClient)
    # 模拟大模型发生通信异常或不可用
    mock_glm.complete_structured.side_effect = RuntimeError("GLM connection refused: connection timed out")
    mock_glm.chat_completion.side_effect = RuntimeError("GLM connection refused: connection timed out")

    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    report = harness.investigate(symptom="自动化设备无响应")

    # 1. 关键断言：final_status 必须显式为 PLANNER_ERROR，禁止伪装成正常收敛或完成
    assert report.final_status == "PLANNER_ERROR"
    assert "PLANNER_ERROR" in report.stop_reason

    # 2. 关键断言：模式未被静默篡改为 deterministic
    assert harness.planner_mode == "llm"

    # 3. 核心结论明确提示排查规划未完成
    assert "排查规划异常" in report.primary_root_cause or "未完成" in report.primary_root_cause
