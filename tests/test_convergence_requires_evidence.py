import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.stop_conditions import StopConditions
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisStatus,
    EvidenceRecord,
    EvidenceTier,
    CaseType,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.hypotheses import HypothesisManager


def test_case_a_single_low_reliability_evidence_rejected_by_guardrail():
    """Case A: 仅有 1 条低可靠度证据时，LLM 申请收敛必须被 Guardrail 拒绝"""
    h1 = Hypothesis(hypothesis_id="H1", description="调度超时", status=HypothesisStatus.UNRESOLVED)
    hypo_mgr = HypothesisManager(initial_hypotheses=[h1])

    state = InvestigationState(
        case_id="c1",
        symptom="设备停顿",
        case_type=CaseType.UNKNOWN_RUNTIME_FAULT,
        hypotheses=[h1],
    )
    # 添加 1 条低可靠度证据
    low_rel_ev = EvidenceRecord(
        evidence_id="EV_001",
        source_type="log",
        source_name="app.log",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="vague timeout message",
        reliability=0.5,
        supports=["H1"],
    )
    state.add_evidence(low_rel_ev)

    can_converge, verdict, reason = StopConditions.validate_convergence(state, hypo_mgr)
    assert can_converge is False
    assert verdict == "REJECTED"
    assert "低可靠度证据" in reason or "INSUFFICIENT_SUPPORT" in reason


def test_case_b_dual_high_quality_evidence_approved_by_guardrail():
    """Case B: 拥有 2 条独立高质量证据且无强反驳时，LLM 申请收敛被 Guardrail 批准"""
    h1 = Hypothesis(hypothesis_id="H1", description="数据库死锁导致任务阻塞", status=HypothesisStatus.UNRESOLVED)
    hypo_mgr = HypothesisManager(initial_hypotheses=[h1])

    state = InvestigationState(
        case_id="c2",
        symptom="月台出库停滞",
        case_type=CaseType.APPLICATION_ERROR,
        hypotheses=[h1],
    )
    # 添加 2 条独立高质量证据
    ev1 = EvidenceRecord(
        evidence_id="EV_001",
        source_type="log",
        source_name="log_search",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="Lock wait timeout exceeded on ordersys_dock_task",
        reliability=0.9,
        supports=["H1"],
    )
    ev2 = EvidenceRecord(
        evidence_id="EV_002",
        source_type="database",
        source_name="db_query",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="SELECT * FROM ordersys_dock_task WHERE status='WAITING'",
        reliability=0.95,
        supports=["H1"],
    )
    state.add_evidence(ev1)
    state.add_evidence(ev2)

    can_converge, verdict, reason = StopConditions.validate_convergence(state, hypo_mgr)
    assert can_converge is True
    assert verdict in ("CONFIRMED", "SUPPORTED")
    assert "批准收敛" in reason
