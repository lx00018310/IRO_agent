import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.llm.glm_client import GlmClient


def test_hypothesis_manager_fails_closed_when_llm_fails():
    """验证 HypothesisManager 在注入 glm_client 时，若 LLM 推演失败，严禁 fallback 到模板，强制置为 error 和空列表"""
    mock_glm = MagicMock(spec=GlmClient)
    # 模拟大模型返回无效或空回复导致解析失败
    mock_glm.chat_completion.return_value = "invalid non-json output"

    hypo_mgr = HypothesisManager(
        symptom="自动化设备无响应",
        glm_client=mock_glm,
    )

    assert hypo_mgr.source == "error"
    assert hypo_mgr.hypotheses == []


def test_harness_fails_closed_when_dynamic_hypothesis_fails():
    """验证 Harness 在 LLM 模式下若假设生成失败，直接中止排查，返回 HYPOTHESIS_GENERATION_ERROR，禁止使用模板继续"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.chat_completion.return_value = "invalid non-json output"

    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    report = harness.investigate(symptom="自动化设备无响应")

    assert report.final_status == "PLANNER_ERROR"
    assert report.stop_reason == "HYPOTHESIS_GENERATION_ERROR"
    assert report.confidence == "Low"
    assert "HYPOTHESIS_GENERATION_ERROR" in report.primary_root_cause
    assert len(report.hypotheses) == 0
