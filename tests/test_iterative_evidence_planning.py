import pytest
from iro_agent.investigation.models import (
    CaseType,
    EvidenceTier,
    InvestigationStep,
    HypothesisStatus,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner
from iro_agent.investigation.priorities import PriorityCalculator


def test_select_next_step_basic():
    """验证能够从候选动作中选出单个最佳动作，且具备高优先级"""
    symptom = "PLC已经发了P2C信号，机器人未响应"
    state = InvestigationState(
        case_id="case_iter_01",
        symptom=symptom,
        case_type=CaseType.PLC_SIGNAL_ERROR,
    )
    hypo_mgr = HypothesisManager(case_type=CaseType.PLC_SIGNAL_ERROR, symptom=symptom)

    step = EvidencePlanner.select_next_step(state, hypo_mgr)
    assert step is not None
    assert isinstance(step, InvestigationStep)
    assert step.step_id == "step_1"
    # PLC 场景下优先选择 PLC 通信日志或边界信号
    assert "plc" in step.evidence_type.lower() or "plc" in step.tool_args.get("keyword", "").lower()


def test_repeat_penalty_prevents_duplicate_steps():
    """验证同一工具动作执行后，重复惩罚生效，不会陷入同一步骤无限循环"""
    symptom = "工控机应用抛出空指针异常"
    state = InvestigationState(
        case_id="case_iter_02",
        symptom=symptom,
        case_type=CaseType.APPLICATION_ERROR,
    )
    hypo_mgr = HypothesisManager(case_type=CaseType.APPLICATION_ERROR, symptom=symptom)

    # 第一轮选择
    first_step = EvidencePlanner.select_next_step(state, hypo_mgr)
    assert first_step is not None
    initial_priority = first_step.priority

    # 模拟执行第一步并记录到 state
    state.record_step_execution(first_step, is_failed=False)

    # 第二轮选择，同一动作若再评估分值必然受惩罚
    second_step = EvidencePlanner.select_next_step(state, hypo_mgr)
    assert second_step is not None
    # 选出的下一步应当换成了其它动作（例如版本核查或数据库）或者分配了更低分
    assert second_step.evidence_type != first_step.evidence_type or second_step.priority < initial_priority
