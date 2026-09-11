import pytest
from iro_agent.investigation.models import (
    CaseType,
    EvidenceTier,
    EvidenceRecord,
    InvestigationStep,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner


def test_replan_after_wait_p2c_evidence():
    """验证获取到 WAIT_P2C 关键日志证据后，规划器自适应调度 P2C 信号边界排查"""
    symptom = "AGV停在月台不动"
    state = InvestigationState(
        case_id="case_replan_01",
        symptom=symptom,
        case_type=CaseType.PLC_SIGNAL_ERROR,
    )
    hypo_mgr = HypothesisManager(case_type=CaseType.PLC_SIGNAL_ERROR, symptom=symptom)

    # 模拟第 1 步执行了普通的通用日志检索
    step1 = InvestigationStep(
        step_id="step_1",
        evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        evidence_type="system_logs",
        tool="log_search",
        reason="检索基础日志",
    )
    state.record_step_execution(step1, is_failed=False)

    # 获得了一条客观证据：日志显示状态机卡在 WAIT_P2C
    ev = EvidenceRecord(
        evidence_id="EV_LOG_01",
        source_type="log_file",
        source_name="application.log",
        tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        raw_summary="State machine is blocked waiting for WAIT_P2C from PLC",
        reliability=1.0,
        relevance=1.0,
        supports=["H2"],
    )
    state.add_evidence(ev)

    # 规划器选择下一步
    next_step = EvidencePlanner.select_next_step(state, hypo_mgr)
    assert next_step is not None
    # 动态重规划动作应当紧密围绕 P2C 展开
    assert "P2C" in next_step.evidence_type.upper() or "P2C" in str(next_step.tool_args).upper()
