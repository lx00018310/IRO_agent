import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisStatus,
    HypothesisAction,
    HypothesisUpdate,
    PlannerDecision,
    DecisionAction,
    EvidenceRecord,
    EvidenceTier,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.planner_validator import PlannerValidator


def test_hypothesis_manager_applies_support_and_contradict():
    mgr = HypothesisManager(
        initial_hypotheses=[
            Hypothesis(hypothesis_id="H1", description="PLC断连", status=HypothesisStatus.UNRESOLVED),
            Hypothesis(hypothesis_id="H2", description="机器人急停", status=HypothesisStatus.UNRESOLVED),
        ]
    )

    updates = [
        HypothesisUpdate(
            action=HypothesisAction.SUPPORT,
            hypothesis_id="H1",
            confidence=0.85,
            evidence_ids=["E001"],
            reason="捕获到PLC心跳丢失日志",
        ),
        HypothesisUpdate(
            action=HypothesisAction.CONTRADICT,
            hypothesis_id="H2",
            confidence=0.10,
            evidence_ids=["E002"],
            reason="机器人自检返回无报警",
        ),
    ]

    applied = mgr.apply_updates(updates)
    assert "SUPPORT:H1" in applied
    assert "CONTRADICT:H2" in applied

    h1 = mgr.get_hypothesis("H1")
    assert h1.status == HypothesisStatus.STRONGLY_SUPPORTED
    assert "E001" in h1.supporting_evidence

    h2 = mgr.get_hypothesis("H2")
    assert h2.status == HypothesisStatus.RULED_OUT
    assert "E002" in h2.contradicting_evidence


def test_planner_validator_approves_valid_updates():
    validator = PlannerValidator()
    decision = PlannerDecision(
        thought="根据已采集证据更新假设",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.9,
                evidence_ids=["E1"],
                reason="日志证实",
            )
        ],
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="log_search",
        tool_arguments={"keyword": "PLC"},
    )
    hypos = [Hypothesis(hypothesis_id="H1", description="PLC断连")]
    evidence_history = [EvidenceRecord(evidence_id="E1", source_type="log", source_name="app.log", tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL, raw_summary="ok")]

    is_valid, err = validator.validate(decision, hypos, evidence_history)
    assert is_valid
    assert err is None
