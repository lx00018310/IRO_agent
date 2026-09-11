from enum import Enum
from typing import Tuple, List, Optional, Any
from iro_agent.investigation.models import HypothesisStatus, InvestigationStep, EvidenceTier
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

    @classmethod
    def validate_convergence(
        cls,
        state: Any,
        hypo_mgr: HypothesisManager,
    ) -> Tuple[bool, str, str]:
        """
        二次审批 LLM Planner 的 CONVERGE 申请 (Harness Guardrail Approval)
        返回: (can_converge: bool, verdict: str, reason: str)
        - verdict: "CONFIRMED" | "SUPPORTED" | "REJECTED"
        """
        top_hypo = hypo_mgr.get_top_hypothesis()
        if not top_hypo:
            return False, "REJECTED", "当前无任何有效排查假设，无法收敛"

        evidence_records = getattr(state, "evidence", [])
        if not evidence_records:
            return False, "REJECTED", "当前尚未收集到任何客观事实证据，严禁未经证据核验的主观收敛 (INSUFFICIENT_SUPPORT)"

        # 区分有效事实证据与错误/观测缺口
        valid_evidence = [e for e in evidence_records if not getattr(e, "is_error", False)]
        if not valid_evidence:
            return False, "REJECTED", "所有已采集证据均为工具异常或观测缺口，无有效事实支撑收敛 (OBSERVABILITY_GAP)"

        # 查找支持与反驳 top_hypo 的证据记录
        supporting_records = [
            e for e in valid_evidence
            if (top_hypo.hypothesis_id in getattr(e, "supports", []) or
                top_hypo.hypothesis_id in getattr(e, "query", {}).get("hypothesis_ids", []) or
                getattr(e, "evidence_id", "") in top_hypo.supporting_evidence)
        ]
        # 若模型未显式绑定 ID，但有高可靠实质性异常/事实证据，且无反驳，自动关联
        if not supporting_records:
            step_matched = []
            for ev in valid_evidence:
                if getattr(ev, "reliability", 1.0) >= 0.8:
                    step_matched.append(ev)
            supporting_records = step_matched

        contradicting_records = [
            e for e in valid_evidence
            if (top_hypo.hypothesis_id in getattr(e, "contradicts", []) or
                getattr(e, "evidence_id", "") in top_hypo.contradicting_evidence)
        ]

        # 强反证阻断
        if contradicting_records or len(top_hypo.contradicting_evidence) > 0:
            return False, "REJECTED", f"当前假设 [{top_hypo.hypothesis_id}] 存在反驳证据，尚未解决逻辑矛盾，无法收敛"

        # 核心 Case A: 只有 1 条低可靠度证据 (reliability < 0.8)
        if len(supporting_records) == 1 and getattr(supporting_records[0], "reliability", 1.0) < 0.8:
            rel = getattr(supporting_records[0], "reliability", 0.5)
            return False, "REJECTED", f"仅有 1 项低可靠度证据 (reliability={rel:.2f})，不足以收敛结案 (INSUFFICIENT_SUPPORT)"

        # Confirmed 条件判定：
        # 条件 A: 1 条 Source-of-Truth 级直接证据 (数据库、系统关键事实，reliability >= 0.95 且 tier 为 1A/1B)
        has_sot = any(
            getattr(e, "reliability", 1.0) >= 0.95 and
            getattr(e, "tier", None) in (EvidenceTier.TIER_1A_RUNTIME_DIGITAL, EvidenceTier.TIER_1B_STATIC_FACTS) and
            any(kw in getattr(e, "source_name", "").lower() for kw in ("db", "database", "config", "table", "sql"))
            for e in supporting_records
        )
        # 条件 B: 至少 2 条独立高质量证据 (len >= 2 且 reliability >= 0.8) 且无反驳证据
        has_dual_high = len(supporting_records) >= 2 and all(getattr(e, "reliability", 1.0) >= 0.8 for e in supporting_records[:2])

        if top_hypo.status == HypothesisStatus.CONFIRMED or has_sot or has_dual_high:
            top_hypo.status = HypothesisStatus.CONFIRMED
            top_hypo.confidence = "High"
            return True, "CONFIRMED", f"关键假设 [{top_hypo.hypothesis_id}: {top_hypo.description}] 已获得确凿证据证实，批准收敛"

        # Supported 条件判定：
        # 至少有 1 条实质性高质量证据 (reliability >= 0.8) 且无反证
        if len(supporting_records) >= 1 and getattr(supporting_records[0], "reliability", 1.0) >= 0.8:
            top_hypo.status = HypothesisStatus.STRONGLY_SUPPORTED
            top_hypo.confidence = "Medium"
            return True, "SUPPORTED", f"当前最可能原因指向 [{top_hypo.hypothesis_id}: {top_hypo.description}]，批准收敛"

        # 多步常规证据支持
        if len(valid_evidence) >= 2 and len(supporting_records) >= 1:
            top_hypo.status = HypothesisStatus.STRONGLY_SUPPORTED
            top_hypo.confidence = "Medium"
            return True, "SUPPORTED", f"当前证据链倾向于 [{top_hypo.hypothesis_id}: {top_hypo.description}]，批准收敛"

        return False, "REJECTED", "当前证据数量或置信度不满足收敛门槛，需继续采集客观事实 (INSUFFICIENT_SUPPORT)"

