from typing import List
from iro_agent.evaluation.models import EvalCase, GradeDetail
from iro_agent.investigation.models import InvestigationReport, EvidenceTier


class PathQualityGrader:
    """
    排查路径质量评测器 (Path Quality Grader)
    评估 Agent 调查过程是否具备资深工业工程师的合理探索逻辑：
    - 优先高可靠数字证据，避免过早进入物理层；
    - 围绕竞争假设取证，避免无效发散或盲目枚举；
    - 无重复无增益查询；
    - 结论明确后及时收敛，无过度排查。
    """

    @classmethod
    def grade(cls, case: EvalCase, report: InvestigationReport) -> GradeDetail:
        violations: List[str] = []
        score_deductions = 0.0

        executed_steps = getattr(report, "investigation_trace", [])
        if not executed_steps:
            return GradeDetail(
                name="path_quality",
                score=1.0,
                passed=True,
                details="无需执行额外工具动作",
            )

        # 1. 检查是否在数字证据未充分前过早进入物理层 (Tier 4)
        for idx, step in enumerate(executed_steps):
            if step.evidence_tier == EvidenceTier.TIER_4_PHYSICAL and idx < 2:
                violations.append("排查路径异常: 尚未完成核心数字要素排查，过早尝试物理带外操作")
                score_deductions += 0.35

        # 2. 检查是否存在重复且无增益的动作序列 (Repeat without gain)
        seen_queries = set()
        repeat_count = 0
        for step in executed_steps:
            key = f"{step.tool}_{step.evidence_type}_{str(step.tool_args)}"
            if key in seen_queries:
                repeat_count += 1
            seen_queries.add(key)

        if repeat_count > 0:
            violations.append(f"发现 {repeat_count} 次重复无效查询，路径缺乏自适应收敛")
            score_deductions += 0.2 * repeat_count

        # 3. 检查排查效率 (步数是否克制合理，不超过 8 步)
        if len(executed_steps) > 8:
            violations.append(f"排查路径过于臃肿 (步数: {len(executed_steps)})，未能敏捷聚焦核心假设")
            score_deductions += 0.15

        # 4. 检查首步质量：第一步通常应当优先查询日志或核心配置/版本 (Tier 1/2)
        if executed_steps[0].evidence_tier in (EvidenceTier.TIER_3_RUNTIME_ENV, EvidenceTier.TIER_4_PHYSICAL):
            violations.append("首步证据层级偏低: 首要排查动作未优先核查 Tier 1/2 核心事实")
            score_deductions += 0.2

        final_score = max(0.0, 1.0 - score_deductions)
        passed = len(violations) == 0

        return GradeDetail(
            name="path_quality",
            score=round(final_score, 3),
            passed=passed,
            details="排查路径聚焦且符合工业诊断工程逻辑" if passed else f"路径缺陷: {'; '.join(violations)}",
            violations=violations,
        )
