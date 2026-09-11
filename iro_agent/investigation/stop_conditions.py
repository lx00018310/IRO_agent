from typing import Tuple, List
from iro_agent.investigation.models import HypothesisStatus, InvestigationStep
from iro_agent.investigation.hypotheses import HypothesisManager


class StopConditions:
    """排查终止条件裁决器 (Stop Conditions: 强结论/确认/证据耗尽/防过度排查)"""

    @classmethod
    def evaluate(
        cls,
        hypo_mgr: HypothesisManager,
        executed_steps: List[InvestigationStep],
        remaining_steps: List[InvestigationStep],
    ) -> Tuple[bool, str]:
        # 1. 直接确认结论 (Direct confirmed conclusion)
        if hypo_mgr.has_confirmed_hypothesis():
            top = hypo_mgr.get_top_hypothesis()
            desc = top.description if top else "明确事实"
            return True, f"直接运行时事实已锁定核心根因: {desc}"

        # 2. 强推论收敛 (Strong conclusion: >=2 项独立高质量支持证据)
        for h in hypo_mgr.hypotheses:
            if h.status == HypothesisStatus.STRONGLY_SUPPORTED and len(h.supporting_evidence) >= 2:
                if not h.contradicting_evidence:
                    return True, f"假设 [{h.hypothesis_id}: {h.description}] 已获得多项独立确凿证据强支持，无逻辑矛盾"

        # 3. 防过度排查 (Do Not Over-Investigate)
        # 若已有单项强烈支持，且后续剩余步骤为无关底层/带外检查，适时收敛
        if hypo_mgr.has_strongly_supported_hypothesis() and len(executed_steps) >= 2:
            top = hypo_mgr.get_top_hypothesis()
            return True, f"关键数字证据链已收敛锁定 [{top.hypothesis_id}: {top.description}]，无需过度查询底层无关系统"

        # 4. 数字证据耗尽 (Digital evidence exhausted)
        if not remaining_steps:
            return True, "所有预定数字要素排查步骤均已执行完毕，数字证据耗尽"

        return False, "继续下一步证据排查"
