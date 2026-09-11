from typing import Dict, Any, Optional
from iro_agent.investigation.models import EvidenceTier, CaseType


class PriorityCalculator:
    """证据层级与排查动作动态优先级计算器 (Dynamic Priority Calculator)"""

    BASE_PRIORITIES = {
        EvidenceTier.TIER_1A_RUNTIME_DIGITAL: 100,
        EvidenceTier.TIER_1B_STATIC_FACTS: 85,
        EvidenceTier.TIER_2_SYSTEM_BOUNDARY: 70,
        EvidenceTier.TIER_3_RUNTIME_ENV: 50,
        EvidenceTier.TIER_4_PHYSICAL: 20,
    }

    @classmethod
    def calculate_priority(
        cls,
        tier: EvidenceTier,
        case_type: CaseType,
        evidence_tag: str = "",
        cost: int = 10,
        info_gain: int = 20,
    ) -> int:
        base = cls.BASE_PRIORITIES.get(tier, 50)
        relevance_bonus = 0
        tag = evidence_tag.lower()

        # 动态场景升权调整
        if case_type == CaseType.PLC_SIGNAL_ERROR or "plc" in tag:
            if tier == EvidenceTier.TIER_2_SYSTEM_BOUNDARY or "plc" in tag:
                relevance_bonus += 40
        elif case_type == CaseType.ROBOT_EXECUTION_ERROR or "robot" in tag:
            if tier == EvidenceTier.TIER_2_SYSTEM_BOUNDARY or "robot" in tag:
                relevance_bonus += 35
        elif case_type == CaseType.CONFIGURATION_ERROR or "config" in tag:
            if "config" in tag:
                relevance_bonus += 35
        elif case_type == CaseType.NETWORK_ENVIRONMENT_ERROR or "network" in tag:
            if tier == EvidenceTier.TIER_3_RUNTIME_ENV or "network" in tag or "port" in tag:
                relevance_bonus += 45
        elif case_type == CaseType.APPLICATION_ERROR:
            if "log" in tag or "db" in tag:
                relevance_bonus += 25

        # 动态优先级公式: Base + Relevance + InfoGain - Cost
        final_priority = base + relevance_bonus + info_gain - cost
        return max(0, final_priority)

    @classmethod
    def score_candidate_step(
        cls,
        step: Any,
        state: Any,
        hypo_mgr: Any,
    ) -> float:
        """
        基于当前排查状态与假设分布，动态评估候选证据动作价值：
        Score =
            base_reliability
          + hypothesis_discrimination_gain
          + case_relevance
          + source_of_truth_bonus
          - execution_cost
          - repeat_penalty
          - low_observability_penalty
        """
        # 1. 证据层级基础可靠度
        base = float(cls.BASE_PRIORITIES.get(step.evidence_tier, 50))

        # 2. 假设区分增益 (hypothesis_discrimination_gain)
        discrimination_gain = 0.0
        active_hypos = [
            h for h in getattr(hypo_mgr, "hypotheses", [])
            if getattr(h, "status", "") in ("UNRESOLVED", "SUPPORTED", "WEAK")
        ]
        if active_hypos:
            matched_active = [
                h for h in active_hypos
                if getattr(h, "hypothesis_id", "") in getattr(step, "hypothesis_ids", [])
            ]
            if len(matched_active) >= 2:
                discrimination_gain += 40.0
            elif len(matched_active) == 1:
                discrimination_gain += 25.0

            # 若该步骤关联假设全部已解决/被排除，信息增益锐减
            all_resolved = all(
                getattr(h, "status", "") in ("CONFIRMED", "RULED_OUT")
                for h in getattr(hypo_mgr, "hypotheses", [])
                if getattr(h, "hypothesis_id", "") in getattr(step, "hypothesis_ids", [])
            )
            if getattr(step, "hypothesis_ids", []) and all_resolved:
                discrimination_gain -= 50.0

        # 3. 业务场景关联度 (case_relevance) 与 最新线索针对性 (recency_value)
        relevance_bonus = 0.0
        recency_value = 0.0
        tag = (f"{step.evidence_type} {step.reason} {step.tool} {str(step.tool_args)}").lower()
        case_type = getattr(state, "case_type", None)
        if case_type == CaseType.PLC_SIGNAL_ERROR and ("plc" in tag or "boundary" in tag or "p2c" in tag):
            relevance_bonus += 35.0
        elif case_type == CaseType.ROBOT_EXECUTION_ERROR and ("robot" in tag or "agv" in tag):
            relevance_bonus += 35.0
        elif case_type == CaseType.CONFIGURATION_ERROR and "config" in tag:
            relevance_bonus += 35.0
        elif case_type == CaseType.APPLICATION_ERROR and ("error" in tag or "log" in tag or "db" in tag):
            relevance_bonus += 25.0
        elif case_type == CaseType.NETWORK_ENVIRONMENT_ERROR and ("network" in tag or "timeout" in tag or "port" in tag):
            relevance_bonus += 40.0

        # 若动作直接对齐已收集证据所暴露的特定异常线索（如 P2C, TIMEOUT, HEARTBEAT 等），赋予 recency_value 增益
        for ev in getattr(state, "evidence", []):
            ev_summary = (getattr(ev, "raw_summary", "") or "").lower()
            for clue in ("p2c", "timeout", "reset", "heartbeat", "deadlock", "nullpointer"):
                if clue in ev_summary and clue in tag:
                    recency_value += 20.0
                    break

        # 4. 权威数据源加成 (source_of_truth_bonus)
        source_of_truth_bonus = 0.0
        if step.evidence_tier == EvidenceTier.TIER_1A_RUNTIME_DIGITAL:
            source_of_truth_bonus += 15.0

        # 5. 执行成本 (execution_cost)
        cost = 10.0
        if step.tool in ("log_search", "version_current", "config_lookup"):
            cost = 5.0
        elif step.tool in ("db_query", "web_fetch"):
            cost = 15.0

        # 6. 重复执行惩罚 (repeat_penalty)
        repeat_penalty = 0.0
        similar_count = 0
        for prev_step in getattr(state, "executed_steps", []):
            if prev_step.tool == step.tool and prev_step.evidence_type == step.evidence_type:
                similar_count += 1
            elif prev_step.tool == step.tool and prev_step.tool_args == step.tool_args:
                similar_count += 2
        if similar_count == 1:
            repeat_penalty = 40.0
        elif similar_count >= 2:
            repeat_penalty = 80.0

        # 7. 低可观测性 / 工具失败惩罚 (low_observability_penalty)
        low_observability_penalty = 0.0
        failed_same_tool = sum(
            1 for fs in getattr(state, "failed_steps", [])
            if getattr(fs, "tool", "") == step.tool
        )
        if failed_same_tool > 0:
            low_observability_penalty = 50.0 * failed_same_tool

        score = (
            base
            + discrimination_gain
            + relevance_bonus
            + recency_value
            + source_of_truth_bonus
            - cost
            - repeat_penalty
            - low_observability_penalty
        )
        return max(0.0, score)

