import pytest
from iro_agent.evaluation.models import EvalCase, EvalExpectation
from iro_agent.investigation.models import (
    CaseType,
    EvidenceTier,
    InvestigationStep,
    InvestigationReport,
)
from iro_agent.evaluation.graders.path_quality import PathQualityGrader


def test_path_quality_high_for_disciplined_digital_path():
    """验证严格遵守 Tier 1/2 数字优先、无冗余重复的排查路径获得满分"""
    case = EvalCase(case_id="c_path_01", input={"symptom": "接口报错"})
    report = InvestigationReport(
        case_type=CaseType.APPLICATION_ERROR,
        symptom="接口报错",
        primary_root_cause="日志捕获NullPointer",
        investigation_trace=[
            InvestigationStep(
                step_id="s1",
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="error_log",
                tool="log_search",
                tool_args={"level": "ERROR"},
                reason="查报错日志",
            ),
            InvestigationStep(
                step_id="s2",
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="version",
                tool="version_current",
                tool_args={},
                reason="核实版本",
            ),
        ],
    )

    grade = PathQualityGrader.grade(case, report)
    assert grade.passed
    assert grade.score == 1.0


def test_path_quality_penalizes_premature_physical_and_repeats():
    """验证过早进入物理带外层及出现重复动作序列时，路径评测被扣分"""
    case = EvalCase(case_id="c_path_02", input={"symptom": "机器人停机"})
    report = InvestigationReport(
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        symptom="机器人停机",
        primary_root_cause="急停触发",
        investigation_trace=[
            # 严重缺陷 1: 首步/次步直接进入 Tier 4 物理带外
            InvestigationStep(
                step_id="s1",
                evidence_tier=EvidenceTier.TIER_4_PHYSICAL,
                evidence_type="physical_button",
                tool="manual_check",
                tool_args={"target": "e-stop"},
                reason="现场按按钮",
            ),
            # 缺陷 2: 重复查询动作
            InvestigationStep(
                step_id="s2",
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="log",
                tool="log_search",
                tool_args={"keyword": "error"},
                reason="查日志",
            ),
            InvestigationStep(
                step_id="s3",
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="log",
                tool="log_search",
                tool_args={"keyword": "error"},
                reason="又查相同日志",
            ),
        ],
    )

    grade = PathQualityGrader.grade(case, report)
    assert not grade.passed
    assert grade.score < 0.6
    assert any("过早尝试物理" in v for v in grade.violations)
    assert any("重复" in v for v in grade.violations)
