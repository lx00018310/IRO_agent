import pytest
from unittest.mock import patch
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.config import IROConfig


def test_no_silent_planner_fallback_when_credentials_missing():
    """验证当 planner_mode='llm' 且未注入 client/缺乏有效 API key 时，严格 Fail Closed，禁止降级为 deterministic"""
    fake_config = IROConfig()
    fake_config.glm.api_key = "MOCK_INVALID_KEY"

    with patch("iro_agent.investigation.harness.get_config", return_value=fake_config):
        harness = InvestigationHarness(planner_mode="llm", glm_client=None, llm_planner=None)

        # 1. 核心断言：planner_mode 保持为 'llm'，绝对不能静默被改成 'deterministic'
        assert harness.planner_mode == "llm"
        assert harness._llm_available is False

        # 2. 调用 investigate 必须显式 Fail Closed
        report = harness.investigate(symptom="设备通信中断")

        assert report.final_status == "PLANNER_ERROR"
        assert report.stop_reason == "AGENTIC_PLANNER_UNAVAILABLE"
        assert report.confidence == "Low"
        assert "AGENTIC_PLANNER_UNAVAILABLE" in report.primary_root_cause
        assert len(report.hypotheses) == 0
