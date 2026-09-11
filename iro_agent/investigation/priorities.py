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
