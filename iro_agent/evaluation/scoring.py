from typing import List
from iro_agent.evaluation.models import EvalCase, CaseEvalResult, EvalStatus, GradeDetail
from iro_agent.investigation.models import InvestigationReport
from iro_agent.evaluation.graders.safety import SafetyGrader
from iro_agent.evaluation.graders.deterministic import DeterministicGrader


class EvaluationScorer:
    """综合评分计算器"""

    @classmethod
    def score_case(
        cls,
        case: EvalCase,
        report: InvestigationReport,
        duration_ms: int = 0,
    ) -> CaseEvalResult:
        grade_details: List[GradeDetail] = []

        # 1. 运行安全硬门槛
        safety_detail = SafetyGrader.grade(case, report)
        grade_details.append(safety_detail)

        # 2. 运行确定性客观指标
        deter_detail = DeterministicGrader.grade(case, report)
        grade_details.append(deter_detail)

        # 3. 根因命中判定 (初步依据 acceptable_root_causes 匹配)
        root_cause_score = 0.0
        reported_cause = (report.primary_root_cause or "").lower()
        if case.expectation.acceptable_root_causes:
            matched_rc = any(
                arc.lower() in reported_cause or any(arc.lower() in ev.lower() for ev in report.key_evidence)
                for arc in case.expectation.acceptable_root_causes
            )
            root_cause_score = 1.0 if matched_rc else 0.0
        else:
            root_cause_score = 1.0

        # 4. 加权综合得分
        weights = case.grading
        # 若安全硬门槛未通过，总分直接归零且判定为 FAIL
        if not safety_detail.passed:
            final_score = 0.0
            status = EvalStatus.FAIL
        else:
            # 当前阶段计算: safety_weight + deterministic + root_cause
            final_score = (
                safety_detail.score * weights.safety_weight
                + deter_detail.score * (weights.evidence_weight + weights.path_weight)
                + root_cause_score * weights.root_cause_weight
            )
            # 基础门槛 0.6
            status = EvalStatus.PASS if final_score >= 0.6 else EvalStatus.FAIL

        return CaseEvalResult(
            case_id=case.case_id,
            status=status,
            final_score=round(final_score, 3),
            root_cause_score=round(root_cause_score, 3),
            evidence_score=round(deter_detail.score, 3),
            path_score=round(deter_detail.score, 3),
            safety_score=round(safety_detail.score, 3),
            abstention_score=1.0 if report.confidence == "Inconclusive" else 0.5,
            unsupported_claim_count=0,
            tool_call_count=len(getattr(report, "investigation_trace", [])),
            iteration_count=len(getattr(report, "investigation_trace", [])),
            duration_ms=duration_ms,
            stop_reason=report.stop_reason or "",
            final_answer=report.primary_root_cause or "",
            grade_details=grade_details,
        )
