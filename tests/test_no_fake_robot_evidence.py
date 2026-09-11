import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.llm.glm_client import GlmClient


def test_no_fake_robot_evidence():
    """断言未配置真实机器人驱动时绝不伪造 ONLINE/STANDBY 假证据"""
    mock_glm = MagicMock(spec=GlmClient)
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    assert "robot_query" in harness.tool_handlers
    res = harness.tool_handlers["robot_query"]()

    # 关键断言：绝不能伪造在线或就绪
    assert res.get("status") != "ONLINE"
    assert res.get("state") != "STANDBY"
    assert res.get("status") == "UNAVAILABLE"
    assert "observability_gap" in str(res.get("error", "")).lower()
