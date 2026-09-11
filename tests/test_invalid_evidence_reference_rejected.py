import pytest
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisAction,
    HypothesisUpdate,
    PlannerDecision,
    DecisionAction,
    EvidenceRecord,
    EvidenceTier,
)
from iro_agent.investigation.planner_validator import PlannerValidator


def test_reject_nonexistent_evidence_reference():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="尝试引用不存在的证据",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.8,
                evidence_ids=["E999"],  # 不存在
                reason="凭空声称支持",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "error"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="假设1")]
    evidence_history = [EvidenceRecord(evidence_id="E001", source_type="log", source_name="app.log", tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, raw_summary="ok")]

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert not is_valid
    assert "不存在的证据 ID 'E999'" in err


def test_reject_user_symptom_as_evidence_reference():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="企图直接把用户提问当证据",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.8,
                evidence_ids=["用户说为什么今天系统卡住了不动了？"],
                reason="用户的话就是证据",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "error"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="假设1")]
    evidence_history = []

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert not is_valid
    assert "非法的 Evidence ID" in err


def test_reject_invalid_confidence_range():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="置信度越界",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=1.5,  # 超出 1.0
                evidence_ids=["E001"],
                reason="超强置信",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "error"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="假设1")]
    evidence_history = [EvidenceRecord(evidence_id="E001", source_type="log", source_name="app.log", tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, raw_summary="ok")]

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert not is_valid
    assert "超出合法区间" in err


def test_reject_support_without_evidence_ids():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="支持假设但无证据支撑",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.9,
                evidence_ids=[],  # 为空
                reason="凭感觉支持",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "error"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="假设1")]
    evidence_history = [EvidenceRecord(evidence_id="E001", source_type="log", source_name="app.log", tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, raw_summary="ok")]

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert not is_valid
    assert "必须绑定具体的客观证据 ID" in err


def test_reject_duplicate_add_statement():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="添加重复假设",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.ADD,
                statement="PLC断连",  # 与已有重合
                confidence=0.5,
                evidence_ids=[],
                reason="重复添加",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "error"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="PLC断连")]
    evidence_history = []

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert not is_valid
    assert "重叠重复" in err
