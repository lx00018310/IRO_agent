import pytest
from iro_agent.evaluation.models import EvalCase, EvalExpectation
from iro_agent.investigation.models import (
    CaseType,
    EvidenceTier,
    InvestigationStep,
    InvestigationReport,
    EvidenceRecord,
)
from iro_agent.evaluation.graders.evidence import EvidenceGroundingGrader


def test_evidence_grounding_passes_with_linked_evidence():
    """验证核心结论有确凿客观证据记录支撑时，证据链评测通过"""
    case = EvalCase(
        case_id="case_grounded_01",
        input={"symptom": "小车在月台等待超时"},
        expectation=EvalExpectation(acceptable_root_causes=["wait_p2c"]),
    )
    report = InvestigationReport(
        case_type=CaseType.PLC_SIGNAL_ERROR,
        symptom="小车在月台等待超时",
        primary_root_cause="后端状态机正在持续等待 WAIT_P2C 信号放行",
        key_evidence=["[TIER_1A] 发现 WAIT_P2C 阻塞日志"],
        evidence_records=[
            EvidenceRecord(
                evidence_id="EV_01",
                source_type="log_search",
                source_name="app_log",
                tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                raw_summary="State is blocked on WAIT_P2C from PLC",
                reliability=1.0,
                supports=["H2"],
            )
        ],
        investigation_trace=[
            InvestigationStep(
                step_id="s1",
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="app_log",
                tool="log_search",
                reason="检查日志",
                result=[{"message": "WAIT_P2C"}],
            )
        ],
    )

    grade = EvidenceGroundingGrader.grade(case, report)
    assert grade.passed
    assert grade.score == 1.0
    assert len(grade.violations) == 0


def test_evidence_grounding_penalizes_unsupported_claims():
    """验证出现凭空断言（未经任何证据支撑的根因或虚构关键依据）时被严厉扣分"""
    case = EvalCase(
        case_id="case_unsupported_01",
        input={"symptom": "机器人不走"},
        expectation=EvalExpectation(),
    )
    report = InvestigationReport(
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        symptom="机器人不走",
        primary_root_cause="机器人减速机机械齿轮发生磨损断裂卡死",  # 凭空断言，无任何相关数字证据
        key_evidence=["现场目测齿轮断裂"],  # 虚构事实
        evidence_records=[],
        investigation_trace=[],
    )

    grade = EvidenceGroundingGrader.grade(case, report)
    assert not grade.passed
    assert grade.score < 1.0
    assert len(grade.violations) >= 1
    assert any("缺乏客观证据链支撑" in v or "无法追溯" in v for v in grade.violations)
