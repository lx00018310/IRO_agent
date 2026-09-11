import pytest
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceTier,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evaluator import EvidenceEvaluator


def test_evidence_evaluator_fact_only():
    """验证各类工具仅提取客观事实规范 (Fact Only)"""
    step_db = InvestigationStep(
        step_id="step_db_empty",
        hypothesis_ids=["H1"],
        evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        evidence_type="task_creation_state",
        tool="db_query",
        tool_args={"sql": "SELECT * FROM tasks WHERE id='t_001'"},
        reason="查任务记录",
    )

    # 数据库返回 0 行
    res_empty = EvidenceEvaluator.evaluate_step(step_db, {"rows": []})
    assert res_empty.verdict == "FACT"
    assert "0 条" in res_empty.detail

    rec_empty = EvidenceEvaluator.create_evidence_record(step_db, {"rows": []}, res_empty)
    assert rec_empty.normalized_fact == res_empty.detail
    assert rec_empty.reliability == 0.95
    assert rec_empty.supports == []
    assert rec_empty.contradicts == []

    # 工具异常提取
    step_gap = InvestigationStep(
        step_id="step_gap",
        hypothesis_ids=["H2"],
        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        evidence_type="gateway",
        tool="web_fetch",
        tool_args={"url": "http://robot-gw/api"},
        reason="检查网关",
    )
    res_gap = EvidenceEvaluator.evaluate_step(step_gap, {"error": "Connection refused by remote host"})
    assert res_gap.verdict == "OBSERVABILITY_GAP"
    rec_gap = EvidenceEvaluator.create_evidence_record(step_gap, {"error": "Connection refused"}, res_gap)
    assert rec_gap.is_error is True
    assert rec_gap.error_type == "OBSERVABILITY_GAP"
    assert rec_gap.reliability == 0.0
