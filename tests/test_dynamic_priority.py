from iro_agent.investigation.models import EvidenceTier, CaseType
from iro_agent.investigation.priorities import PriorityCalculator


def test_default_tier_order():
    """验证默认情况下高层数字证据优先级高于底层环境与物理要素"""
    p_1a = PriorityCalculator.calculate_priority(EvidenceTier.TIER_1A_RUNTIME_DIGITAL, CaseType.APPLICATION_ERROR)
    p_1b = PriorityCalculator.calculate_priority(EvidenceTier.TIER_1B_STATIC_FACTS, CaseType.APPLICATION_ERROR)
    p_2 = PriorityCalculator.calculate_priority(EvidenceTier.TIER_2_SYSTEM_BOUNDARY, CaseType.APPLICATION_ERROR)
    p_3 = PriorityCalculator.calculate_priority(EvidenceTier.TIER_3_RUNTIME_ENV, CaseType.APPLICATION_ERROR)
    p_4 = PriorityCalculator.calculate_priority(EvidenceTier.TIER_4_PHYSICAL, CaseType.APPLICATION_ERROR)

    assert p_1a > p_1b > p_2 > p_3 > p_4


def test_plc_dynamic_promotion():
    """验证遇到 PLC 信号故障时，PLC 系统边界与通信证据被动态前置提升"""
    p_plc_promoted = PriorityCalculator.calculate_priority(
        EvidenceTier.TIER_2_SYSTEM_BOUNDARY, CaseType.PLC_SIGNAL_ERROR, evidence_tag="plc_log"
    )
    p_static_code = PriorityCalculator.calculate_priority(
        EvidenceTier.TIER_1B_STATIC_FACTS, CaseType.PLC_SIGNAL_ERROR, evidence_tag="code"
    )

    # PLC 边界通信日志在 PLC 故障场景下应超过一般性静态代码审查
    assert p_plc_promoted > p_static_code


def test_config_dynamic_promotion():
    """验证遇到配置故障时，配置检索证据被动态提权"""
    p_cfg = PriorityCalculator.calculate_priority(
        EvidenceTier.TIER_1A_RUNTIME_DIGITAL, CaseType.CONFIGURATION_ERROR, evidence_tag="config_lookup"
    )
    p_normal_log = PriorityCalculator.calculate_priority(
        EvidenceTier.TIER_1A_RUNTIME_DIGITAL, CaseType.APPLICATION_ERROR, evidence_tag="error_log"
    )
    assert p_cfg >= p_normal_log
