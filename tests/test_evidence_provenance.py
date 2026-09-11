import pytest
from iro_agent.investigation.models import (
    EvidenceTier,
    EvidenceRecord,
    CaseType,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.trace import InvestigationTrace, TraceIteration


def test_evidence_record_provenance():
    ev = EvidenceRecord(
        evidence_id="EV_001",
        source_type="db_table",
        source_name="agv_task_order",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        query={"sql": "SELECT status FROM agv_task_order WHERE task_id = 'T100'"},
        raw_summary="task_id T100 status is WAITING_P2C",
        timestamp="2026-09-11T10:00:00Z",
        reliability=1.0,
        relevance=0.9,
        supports=["H1"],
        contradicts=["H2"],
        provenance={"reader": "DatabaseReader", "execution_time_ms": 45},
    )

    assert ev.evidence_id == "EV_001"
    assert ev.tier == EvidenceTier.TIER_1A_RUNTIME_DIGITAL
    assert ev.provenance["reader"] == "DatabaseReader"
    assert not ev.is_error
    assert "H1" in ev.supports
    assert "H2" in ev.contradicts


def test_user_symptom_is_not_confirmed_evidence():
    """验证用户主观陈述不能被直接当作 Tier 1 客观已确认证据"""
    user_symptom = "PLC已经发了P2C，但是AGV没动，PLC肯定坏了"
    state = InvestigationState(
        case_id="case_003",
        symptom=user_symptom,
        case_type=CaseType.PLC_SIGNAL_ERROR,
    )

    # 初始状态下，无任何证据记录
    assert len(state.evidence) == 0
    assert len(state.get_confirmed_evidence()) == 0

    # 模拟外部错误试图将用户描述伪装为证据
    fake_user_evidence = EvidenceRecord(
        evidence_id="USER_01",
        source_type="user_claim",
        source_name="user_input",
        tier=EvidenceTier.TIER_4_PHYSICAL,
        raw_summary=user_symptom,
        reliability=0.2,  # 用户主观描述可靠度必须低
        supports=["H_plc_hardware_error"],
    )
    state.add_evidence(fake_user_evidence)

    # get_confirmed_evidence() 门槛为 reliability >= 0.8，绝不能包含用户口述
    confirmed = state.get_confirmed_evidence()
    assert len(confirmed) == 0


def test_investigation_trace_recording():
    trace = InvestigationTrace(
        case_id="case_trace_01",
        symptom="机器人通信掉线",
    )
    trace.record_iteration(
        iteration=1,
        hypotheses_before=[{"id": "H1", "status": "UNRESOLVED"}],
        candidate_steps=[{"step_id": "S1", "tool": "log_search"}],
        selected_step={"step_id": "S1", "tool": "log_search"},
        selection_reason="优先检查网络连接超时日志",
        tool_call={"tool": "log_search", "args": {"keyword": "timeout"}},
        tool_result_summary="发现 3 条 Connection reset by peer 日志",
        evidence={"evidence_id": "EV_01", "reliability": 0.9},
        hypotheses_after=[{"id": "H1", "status": "STRONGLY_SUPPORTED"}],
        stop_decision={"should_stop": False, "reason": ""},
    )

    d = trace.to_dict()
    assert d["case_id"] == "case_trace_01"
    assert len(d["iterations"]) == 1
    assert d["iterations"][0]["selected_step"]["step_id"] == "S1"
    assert d["iterations"][0]["selection_reason"] == "优先检查网络连接超时日志"
