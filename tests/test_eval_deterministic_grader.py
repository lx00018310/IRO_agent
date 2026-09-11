import pytest
from iro_agent.evaluation.models import EvalCase, EvalExpectation
from iro_agent.investigation.models import (
    CaseType,
    EvidenceTier,
    InvestigationStep,
    InvestigationReport,
    EvidenceRecord,
)
from iro_agent.evaluation.graders.deterministic import DeterministicGrader


def test_deterministic_grader_catches_forbidden_claims():
    case = EvalCase(
        case_id="c_deter_01",
        input={"symptom": "机器人停止动作"},
        expectation=EvalExpectation(
            forbidden_claims=["硬件损坏", "电机烧毁"],
            required_evidence_types=["robot_log"],
        ),
    )
    report = InvestigationReport(
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        symptom="机器人停止动作",
        primary_root_cause="疑似硬件损坏导致停机",  # 命中 forbidden_claims
        key_evidence=["日志无异常"],
        investigation_trace=[
            InvestigationStep(
                step_id="s1",
                evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                evidence_type="robot_log",
                tool="log_search",
                reason="检查机器人日志",
            )
        ],
    )

    res = DeterministicGrader.grade(case, report)
    assert not res.passed
    assert res.score < 1.0
    assert any("硬件损坏" in v for v in res.violations)


def test_deterministic_grader_catches_user_symptom_as_evidence():
    case = EvalCase(
        case_id="c_deter_02",
        input={"symptom": "用户称PLC损坏"},
        expectation=EvalExpectation(required_evidence_types=[]),
    )
    report = InvestigationReport(
        case_type=CaseType.PLC_SIGNAL_ERROR,
        symptom="用户称PLC损坏",
        primary_root_cause="分析中",
        evidence_records=[
            EvidenceRecord(
                evidence_id="ev_fake",
                source_type="user_claim",
                source_name="user_input",
                tier=EvidenceTier.TIER_4_PHYSICAL,
                raw_summary="用户主观认为损坏",
                reliability=0.9,  # 严重违规：用户口述被标为 >= 0.8 的高可信证据
            )
        ],
    )

    res = DeterministicGrader.grade(case, report)
    assert not res.passed
    assert any("用户口述" in v for v in res.violations)
