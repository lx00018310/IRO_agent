from enum import Enum
from typing import Tuple, List, Optional, Any
from iro_agent.investigation.models import HypothesisStatus, InvestigationStep
from iro_agent.investigation.hypotheses import HypothesisManager


class StopReasonCode(str, Enum):
    """标准化调查终止原因代码"""
    CONFIRMED_CAUSE = "CONFIRMED_CAUSE"
    STRONG_CONVERGENCE = "STRONG_CONVERGENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DIGITAL_EVIDENCE_EXHAUSTED = "DIGITAL_EVIDENCE_EXHAUSTED"
    OBSERVABILITY_GAP = "OBSERVABILITY_GAP"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    REPEATED_NO_GAIN = "REPEATED_NO_GAIN"
    TOOL_FAILURE_BLOCKED = "TOOL_FAILURE_BLOCKED"
    PHYSICAL_ESCALATION = "PHYSICAL_ESCALATION"


class StopConditions:
    """排查终止条件裁决器 (Stop Conditions: 强结论/确认/证据耗尽/防过度排查/预算控制)"""

    @classmethod
    def evaluate(
        cls,
        hypo_mgr: HypothesisManager,
        executed_steps: List[InvestigationStep],
        remaining_steps: List[InvestigationStep],
    ) -> Tuple[bool, str]:
        """兼容旧版列表驱动的停止判断"""
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
        if hypo_mgr.has_strongly_supported_hypothesis() and len(executed_steps) >= 2:
            top = hypo_mgr.get_top_hypothesis()
            return True, f"关键数字证据链已收敛锁定 [{top.hypothesis_id}: {top.description}]，无需过度查询底层无关系统"

        # 4. 数字证据耗尽 (Digital evidence exhausted)
        if not remaining_steps:
            return True, "所有预定数字要素排查步骤均已执行完毕，数字证据耗尽"

        return False, "继续下一步证据排查"

    @classmethod
    def evaluate_state(
        cls,
        state: Any,
        hypo_mgr: HypothesisManager,
    ) -> Tuple[bool, str, str]:
        """
        基于 InvestigationState 的动态收敛与停止裁决：
        返回 (should_stop, reason_detail, stop_reason_code)
        """
        # 1. 预算耗尽硬门槛
        if getattr(state, "is_budget_exhausted", lambda: False)():
            return True, "排查已达最大轮次或工具调用预算限制", StopReasonCode.BUDGET_EXHAUSTED.value

        # 2. 直接事实确认根因 (Single SoT or multiple confirmed)
        if hypo_mgr.has_confirmed_hypothesis():
            top = hypo_mgr.get_top_hypothesis()
            desc = top.description if top else "明确事实"
            return True, f"直接运行时事实已锁定核心根因: {desc}", StopReasonCode.CONFIRMED_CAUSE.value

        # 3. 强结论收敛 (>= 2 项独立确凿证据，无反驳)
        for h in hypo_mgr.hypotheses:
            if h.status == HypothesisStatus.STRONGLY_SUPPORTED and len(h.supporting_evidence) >= 2:
                if not h.contradicting_evidence:
                    return (
                        True,
                        f"假设 [{h.hypothesis_id}: {h.description}] 已获得多项独立确凿证据强支持，无逻辑矛盾",
                        StopReasonCode.STRONG_CONVERGENCE.value,
                    )

        # 4. 关键证据链收敛锁定，防止过度排查
        executed_steps = getattr(state, "executed_steps", [])
        if hypo_mgr.has_strongly_supported_hypothesis() and len(executed_steps) >= 2:
            top = hypo_mgr.get_top_hypothesis()
            return (
                True,
                f"关键数字证据链已收敛锁定 [{top.hypothesis_id}: {top.description}]，无需过度查询底层无关系统",
                StopReasonCode.STRONG_CONVERGENCE.value,
            )

        # 5. 关键工具调用连续失败 / 观测严重受阻
        failed_steps = getattr(state, "failed_steps", [])
        if len(failed_steps) >= 3:
            return True, "多个关键诊断工具连续执行异常，排查路径受阻", StopReasonCode.TOOL_FAILURE_BLOCKED.value

        # 6. 连续无收益检查 (连续两步未新增有效信息且假设无法区分)
        if len(executed_steps) >= 4:
            recent_evals = [s.evaluation for s in executed_steps[-2:] if hasattr(s, "evaluation")]
            if recent_evals and all(ev in ("MISSING", "INCONCLUSIVE") for ev in recent_evals):
                # 检查假设是否长期未决
                unresolved_count = sum(1 for h in hypo_mgr.hypotheses if h.status == HypothesisStatus.UNRESOLVED)
                if unresolved_count >= 2:
                    return True, "连续排查未产生有效信息增益，无法进一步区分竞争假设", StopReasonCode.REPEATED_NO_GAIN.value

        return False, "继续下一步证据排查", ""

