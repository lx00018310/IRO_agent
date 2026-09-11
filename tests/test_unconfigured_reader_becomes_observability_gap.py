import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.evaluator import EvidenceEvaluator
from iro_agent.investigation.models import InvestigationStep, EvidenceTier
from iro_agent.llm.glm_client import GlmClient


def test_unconfigured_reader_becomes_observability_gap():
    """断言未配置的物理 Reader 工具输出被严格正规化为 OBSERVABILITY_GAP，可靠性置为 0.0"""
    mock_glm = MagicMock(spec=GlmClient)
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    raw_output = harness.tool_handlers["plc_read"](address="M10.0")

    step = InvestigationStep(
        step_id="step_plc",
        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        evidence_type="plc_point",
        tool="plc_read",
        tool_args={"address": "M10.0"},
        reason="测试PLC连接",
    )

    eval_res = EvidenceEvaluator.evaluate_step(step, raw_output)
    assert eval_res.verdict == "OBSERVABILITY_GAP"

    record = EvidenceEvaluator.create_evidence_record(step, raw_output, eval_res)
    assert record.is_error is True
    assert record.error_type == "OBSERVABILITY_GAP"
    assert record.reliability == 0.0
