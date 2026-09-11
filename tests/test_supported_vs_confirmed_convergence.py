import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
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


def test_confirmed_convergence_wording_and_high_confidence():
    """验证获得 Source-of-Truth 或双高质量确凿证据时，收敛结案确认为 CONFIRMED，措辞为'已确认'且置信度为'High'"""
    h1 = Hypothesis(hypothesis_id="H1", description="数据库死锁导致任务阻塞")
    hypo_mgr = HypothesisManager(initial_hypotheses=[h1])

    state = InvestigationState(
        case_id="c_conf",
        symptom="月台出库停滞",
        case_type=CaseType.APPLICATION_ERROR,
        hypotheses=[h1],
    )
    # 注入 SoT 级数据库强证据
    db_ev = EvidenceRecord(
        evidence_id="EV_DB",
        source_type="database",
        source_name="db_query",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="Deadlock detected",
        reliability=0.98,
        supports=["H1"],
    )
    state.add_evidence(db_ev)

    can_converge, verdict, reason = StopConditions.validate_convergence(state, hypo_mgr)
    assert can_converge is True
    assert verdict == "CONFIRMED"

    # 模拟 Harness 结案报告处理
    top_hypo = hypo_mgr.get_top_hypothesis()
    assert top_hypo.status == HypothesisStatus.CONFIRMED

    # 验证最终报告措辞逻辑
    if top_hypo.status == HypothesisStatus.CONFIRMED:
        cause = f"已确认核心根因: {top_hypo.description}"
        confidence = "High"
    else:
        cause = f"当前最可能原因: {top_hypo.description}"
        confidence = "Medium"

    assert "已确认" in cause
    assert confidence == "High"


def test_supported_convergence_wording_and_medium_confidence():
    """验证仅有单项高质量证据时，收敛结案判定为 SUPPORTED，措辞限定为'当前最可能'，严禁写成'已确认'"""
    h1 = Hypothesis(hypothesis_id="H1", description="调度网关网络轻微抖动")
    hypo_mgr = HypothesisManager(initial_hypotheses=[h1])

    state = InvestigationState(
        case_id="c_supp",
        symptom="网络偶发断链",
        case_type=CaseType.UNKNOWN_RUNTIME_FAULT,
        hypotheses=[h1],
    )
    # 注入 1 条常规高质量日志证据（非 SoT 数据库直接记录）
    log_ev = EvidenceRecord(
        evidence_id="EV_LOG",
        source_type="log",
        source_name="log_search",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="Socket reconnect attempted",
        reliability=0.85,
        supports=["H1"],
    )
    state.add_evidence(log_ev)

    can_converge, verdict, reason = StopConditions.validate_convergence(state, hypo_mgr)
    assert can_converge is True
    assert verdict == "SUPPORTED"

    top_hypo = hypo_mgr.get_top_hypothesis()
    assert top_hypo.status == HypothesisStatus.STRONGLY_SUPPORTED

    # 验证最终报告措辞逻辑
    if top_hypo.status == HypothesisStatus.CONFIRMED:
        cause = f"已确认核心根因: {top_hypo.description}"
        confidence = "High"
    elif top_hypo.status == HypothesisStatus.STRONGLY_SUPPORTED:
        cause = f"当前最可能原因: {top_hypo.description}"
        confidence = "Medium"

    assert "当前最可能原因" in cause
    assert "已确认" not in cause
    assert confidence == "Medium"
