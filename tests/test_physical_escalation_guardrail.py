import pytest
from iro_agent.investigation.physical_escalation import PhysicalEscalation
from iro_agent.investigation.models import InvestigationStep, EvidenceTier, CaseType, Hypothesis, HypothesisStatus
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.state import InvestigationState


def test_physical_escalation_guardrail_logic():
    """验证 PhysicalEscalation.should_escalate 的严格防御逻辑"""
    mgr = HypothesisManager(
        initial_hypotheses=[
            Hypothesis(hypothesis_id="H1", description="任务未下发", status=HypothesisStatus.UNRESOLVED)
        ]
    )

    state = InvestigationState(case_id="c1", symptom="异常", case_type=CaseType.ROBOT_EXECUTION_ERROR)

    # 1. 步数不足 2 步 -> 拒绝
    can_esc, reason = PhysicalEscalation.should_escalate(state, mgr)
    assert can_esc is False
    assert "尚不充分" in reason

    # 2. 模拟执行了 2 步，但包含工具失败 -> 拒绝
    step1 = InvestigationStep(step_id="s1", evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, evidence_type="log", tool="log_search", reason="查日志")
    step2 = InvestigationStep(step_id="s2", evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, evidence_type="task_status", tool="db_query", reason="查状态")
    state.record_step_execution(step1, is_failed=True)
    state.record_step_execution(step2, is_failed=False)

    can_esc, reason = PhysicalEscalation.should_escalate(state, mgr)
    assert can_esc is False
    assert "观测断链" in reason

    # 3. 正常执行 2 步覆盖日志与核心状态，但已有假设被证实 -> 拒绝
    state_ok = InvestigationState(case_id="c2", symptom="异常", case_type=CaseType.ROBOT_EXECUTION_ERROR)
    state_ok.record_step_execution(step1, is_failed=False)
    state_ok.record_step_execution(step2, is_failed=False)
    mgr.confirm("H1", reason="已证实", evidence="E1")

    can_esc, reason = PhysicalEscalation.should_escalate(state_ok, mgr)
    assert can_esc is False
    assert "确凿" in reason

    # 4. 正常执行 2 步覆盖日志与核心状态，假设均无法证实且无软件异常 -> 允许升级
    mgr_unresolved = HypothesisManager(
        initial_hypotheses=[
            Hypothesis(hypothesis_id="H2", description="未知异常", status=HypothesisStatus.UNRESOLVED)
        ]
    )
    can_esc, reason = PhysicalEscalation.should_escalate(state_ok, mgr_unresolved)
    assert can_esc is True
    assert "建议升级现场物理带外排查" in reason
