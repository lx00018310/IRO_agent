from iro_agent.investigation.models import CaseType, EvidenceTier, InvestigationStep
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.stop_conditions import StopConditions


def test_stop_on_confirmed():
    """验证直接确认假设成立时立即停止排查"""
    mgr = HypothesisManager(case_type=CaseType.APPLICATION_ERROR, symptom="NullPointer")
    mgr.confirm("H1", reason="捕获确凿堆栈", evidence="LOG_EX_01")

    should_stop, reason = StopConditions.evaluate(hypo_mgr=mgr, executed_steps=[], remaining_steps=[])
    assert should_stop
    assert "直接运行时事实已锁定" in reason


def test_stop_on_strong_conclusion_with_dual_evidence():
    """验证获得两项独立确凿支持证据后提前收敛 (Strong Conclusion)"""
    mgr = HypothesisManager(case_type=CaseType.ROBOT_EXECUTION_ERROR, symptom="小车不走")
    mgr.strongly_support("H3", reason="机器人返回408", evidence="LOG_408")
    mgr.strongly_support("H3", reason="接口连通性测试失败", evidence="PING_FAIL")

    step1 = InvestigationStep(
        step_id="s1", evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY, evidence_type="log", tool="log_search", reason="查日志"
    )
    should_stop, reason = StopConditions.evaluate(hypo_mgr=mgr, executed_steps=[step1], remaining_steps=[step1])
    assert should_stop
    assert "多项独立确凿证据强支持" in reason


def test_stop_on_exhausted_digital_evidence():
    """验证剩余数字证据步骤耗尽时停止"""
    mgr = HypothesisManager(case_type=CaseType.UNKNOWN_RUNTIME_FAULT, symptom="现场异常")
    step1 = InvestigationStep(
        step_id="s1", evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, evidence_type="log", tool="log_search", reason="查日志"
    )
    should_stop, reason = StopConditions.evaluate(hypo_mgr=mgr, executed_steps=[step1], remaining_steps=[])
    assert should_stop
    assert "数字证据耗尽" in reason
