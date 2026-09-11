from typing import List, Dict, Any
from iro_agent.evaluation.models import EvalCase, GradeDetail
from iro_agent.investigation.models import InvestigationReport, EvidenceTier


class DeterministicGrader:
    """
    确定性客观指标评测器 (Deterministic Grader)
    负责评判调用预算、必要数据源覆盖、禁止论断规避、引用证据有效性等客观事实。
    """

    MAX_TOOL_CALL_BUDGET = 12
    MAX_ITERATION_BUDGET = 10

    @classmethod
    def grade(cls, case: EvalCase, report: InvestigationReport) -> GradeDetail:
        violations: List[str] = []
        score_deductions = 0.0

        executed_steps = getattr(report, "investigation_trace", [])
        evidence_records = getattr(report, "evidence_records", [])

        # 1. 预算超限判定
        if len(executed_steps) > cls.MAX_TOOL_CALL_BUDGET:
            violations.append(f"工具调用总数超预算: {len(executed_steps)} > {cls.MAX_TOOL_CALL_BUDGET}")
            score_deductions += 0.3

        # 2. 检查禁止主张 (Forbidden Claims)
        report_text = f"{report.primary_root_cause or ''} {' '.join(report.key_evidence)}".lower()
        for fc in case.expectation.forbidden_claims:
            if fc.lower() in report_text:
                violations.append(f"包含禁止的主张/武断推论: {fc}")
                score_deductions += 0.4

        # 3. 检查必要证据数据源是否被有效获取 (Required Evidence Types，发生工具报错不计入有效获取)
        valid_steps = [
            s for s in executed_steps
            if not (isinstance(getattr(s, "result", None), dict) and getattr(s, "result", {}).get("error"))
        ]
        valid_evidence_types = [s.evidence_type.lower() for s in valid_steps if hasattr(s, "evidence_type")]
        valid_tools = [s.tool.lower() for s in valid_steps if hasattr(s, "tool")]
        for req in case.expectation.required_evidence_types:
            req_lower = req.lower()
            matched = any(req_lower in et for et in valid_evidence_types) or any(req_lower in t for t in valid_tools)
            if not matched:
                violations.append(f"缺失或未能成功采集到用例要求的核心证据源: {req}")
                score_deductions += 0.3


        # 4. 严禁将用户 symptom 标为已确认事实 (Symptom is not evidence)
        for ev in evidence_records:
            if getattr(ev, "source_type", "") in ("user_claim", "user_symptom", "user_input"):
                if getattr(ev, "reliability", 0.0) >= 0.8:
                    violations.append("严重违规: 将用户口述/主观描述直接标记为高可靠已确认事实")
                    score_deductions += 0.5

        final_score = max(0.0, 1.0 - score_deductions)
        passed = len(violations) == 0

        return GradeDetail(
            name="deterministic_rules",
            score=final_score,
            passed=passed,
            details="确定性客观指标符合规范" if passed else f"违规项: {'; '.join(violations)}",
            violations=violations,
        )
