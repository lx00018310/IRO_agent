from typing import List
from iro_agent.evaluation.models import EvalCase, GradeDetail
from iro_agent.investigation.models import InvestigationReport


class EvidenceGroundingGrader:
    """
    证据链落地评测器 (Evidence Grounding Grader)
    校验最终核心主张 (Claims) 是否均具有确凿的客观证据支撑，
    严禁出现无证据佐证的强断言 (Unsupported Claims / 凭空脑补)。
    """

    @classmethod
    def grade(cls, case: EvalCase, report: InvestigationReport) -> GradeDetail:
        violations: List[str] = []
        unsupported_count = 0

        evidence_records = getattr(report, "evidence_records", [])
        executed_steps = getattr(report, "investigation_trace", [])
        primary_cause = (report.primary_root_cause or "").strip()

        # 1. 检查核心根因是否有对应证据支撑
        if primary_cause and "经多维" not in primary_cause and "不足" not in primary_cause:
            # 必须至少有一条有效证据支持该根因对应假设或领域
            has_supporting_evidence = False
            for ev in evidence_records:
                if not ev.is_error and ev.reliability >= 0.7:
                    # 检查是否有支持假设或文本重合
                    if ev.supports or any(word in ev.raw_summary for word in primary_cause.split()):
                        has_supporting_evidence = True
                        break

            if not has_supporting_evidence and not executed_steps:
                violations.append(f"核心根因 [{primary_cause}] 缺乏客观证据链支撑 (未见相关支持证据记录)")
                unsupported_count += 1

        # 2. 检查关键依据 (Key Evidence) 是否存在虚构证据
        for ke in report.key_evidence:
            clean_ke = ke
            if "]" in clean_ke:
                clean_ke = clean_ke[clean_ke.find("]")+1:].strip()

            matched = False
            # 检查步骤原因与结果
            for s in executed_steps:
                s_text = f"{getattr(s, 'reason', '')} {getattr(s, 'evidence_type', '')} {str(getattr(s, 'result', ''))}".lower()
                if clean_ke.lower() in s_text or any(token in s_text for token in clean_ke.lower().split() if len(token) > 3):
                    matched = True
                    break

            # 检查证据记录摘要
            if not matched:
                for ev in evidence_records:
                    ev_text = f"{getattr(ev, 'raw_summary', '')} {getattr(ev, 'source_name', '')}".lower()
                    if clean_ke.lower() in ev_text or any(token in ev_text for token in clean_ke.lower().split() if len(token) > 3):
                        matched = True
                        break

            if not matched:
                violations.append(f"关键依据包含无法追溯来源的事实主张: {ke[:40]}")
                unsupported_count += 1


        # 扣分：每项 unsupported claim 扣除 0.3
        score = max(0.0, 1.0 - unsupported_count * 0.3)
        passed = unsupported_count == 0

        return GradeDetail(
            name="evidence_grounding",
            score=round(score, 3),
            passed=passed,
            details=f"证据链合规，无凭空断言 (未支撑主张数: {unsupported_count})" if passed else f"发现 {unsupported_count} 处缺乏证据的强主张: {'; '.join(violations)}",
            violations=violations,
        )
