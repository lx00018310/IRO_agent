import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.llm.glm_client import GlmClient


def test_no_fake_plc_evidence():
    """断言未配置真实 PLC Reader 时绝不伪造 READ_SUCCESS/val=0 假证据"""
    mock_glm = MagicMock(spec=GlmClient)
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    assert "plc_read" in harness.tool_handlers
    res = harness.tool_handlers["plc_read"](address="D100")

    # 关键断言：绝不能返回虚假正常读取事实
    assert res.get("status") != "READ_SUCCESS"
    assert "val" not in res
    assert res.get("status") == "UNAVAILABLE"
    assert "observability_gap" in str(res.get("error", "")).lower()
