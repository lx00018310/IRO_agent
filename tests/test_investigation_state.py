import pytest
from iro_agent.investigation.models import (
    CaseType,
    Hypothesis,
    HypothesisStatus,
    InvestigationStep,
    EvidenceTier,
    EvidenceRecord,
)
from iro_agent.investigation.state import InvestigationState


def test_investigation_state_initialization():
    state = InvestigationState(
        case_id="case_test_001",
        symptom="PLC 已经发送 P2C，但机器人未动作",
        case_type=CaseType.PLC_SIGNAL_ERROR,
    )
    assert state.case_id == "case_test_001"
    assert state.case_type == CaseType.PLC_SIGNAL_ERROR
    assert state.iteration == 0
    assert state.tool_calls == 0
    assert len(state.evidence) == 0
    assert len(state.executed_steps) == 0
    assert len(state.failed_steps) == 0
    assert not state.is_budget_exhausted()
    assert not state.has_tool_failure()


def test_investigation_state_evidence_and_steps():
    state = InvestigationState(
        case_id="case_test_002",
        symptom="后端状态机报错",
        case_type=CaseType.APPLICATION_ERROR,
        max_iterations=2,
        max_tool_calls=2,
    )

    # 记录普通执行步骤
    step1 = InvestigationStep(
        step_id="S01",
        evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        evidence_type="LOG",
        tool="log_search",
        reason="检查异常日志",
    )
    state.record_step_execution(step1, is_failed=False)
    assert state.tool_calls == 1
    assert len(state.executed_steps) == 1

    # 添加客观证据记录
    ev1 = EvidenceRecord(
        evidence_id="E01",
        source_type="log_file",
        source_name="application.log",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        query={"keyword": "NullPointerException"},
        raw_summary="发现 NullPointerException 崩溃日志",
        reliability=0.95,
        relevance=0.9,
        supports=["H1"],
    )
    state.add_evidence(ev1)
    assert len(state.evidence) == 1
    assert len(state.get_confirmed_evidence()) == 1

    # 记录工具失败步骤
    step2 = InvestigationStep(
        step_id="S02",
        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        evidence_type="PLC_STATE",
        tool="plc_query",
        reason="查询PLC寄存器",
    )
    state.record_step_execution(step2, is_failed=True)
    assert state.tool_calls == 2
    assert len(state.failed_steps) == 1
    assert state.has_tool_failure()

    # 预算检查
    assert state.is_budget_exhausted()
