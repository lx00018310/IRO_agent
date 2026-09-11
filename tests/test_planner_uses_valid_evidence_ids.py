import pytest
from iro_agent.investigation.planner_validator import PlannerValidator
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    HypothesisAction,
    HypothesisUpdate,
    Hypothesis,
    EvidenceRecord,
    EvidenceTier,
)


def test_planner_validator_accepts_valid_evidence_ids_and_rejects_hallucinated_ids():
    """验证 PlannerValidator 严格检验 Evidence ID：允许存在的合法证据引用，拒绝凭空编造的证据 ID"""
    validator = PlannerValidator()

    hypos = [Hypothesis(hypothesis_id="H1", description="调度服务通信超时")]
    evidences = [
        EvidenceRecord(
            evidence_id="EV_001",
            source_type="log",
            source_name="log_search",
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
            raw_summary="error timeout",
        )
    ]

    # 1. 引用合法且已存在的 EV_001，校验必须通过
    valid_decision = PlannerDecision(
        thought="根据 EV_001 日志证据，支持 H1 假设",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.9,
                evidence_ids=["EV_001"],
                reason="日志记录了超时",
            )
        ],
        decision=DecisionAction.CONVERGE,
        reason="事实确凿，收敛结案",
    )
    ok, err = validator.validate(valid_decision, hypotheses=hypos, evidence_history=evidences)
    assert ok is True
    assert err is None

    # 2. 编造不存在的 FAKE_EV_999，校验必须强阻断拒绝
    hallucinated_decision = PlannerDecision(
        thought="猜测是硬件问题",
        hypothesis_updates=[
            HypothesisUpdate(
                action=HypothesisAction.SUPPORT,
                hypothesis_id="H1",
                confidence=0.9,
                evidence_ids=["FAKE_EV_999"],
                reason="幻觉编造的证据",
            )
        ],
        decision=DecisionAction.CONVERGE,
        reason="非法收敛",
    )
    ok2, err2 = validator.validate(hallucinated_decision, hypotheses=hypos, evidence_history=evidences)
    assert ok2 is False
    assert "不存在的证据 ID" in err2
    assert "FAKE_EV_999" in err2
