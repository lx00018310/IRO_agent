import pytest
from iro_agent.investigation.models import CaseType, HypothesisStatus
from iro_agent.investigation.hypotheses import HypothesisManager


def test_hypothesis_generation_quantities():
    """验证各类典型场景生成的初始假设数量在 2~6 个之间"""
    for c_type in [
        CaseType.ROBOT_EXECUTION_ERROR,
        CaseType.PLC_SIGNAL_ERROR,
        CaseType.CONFIGURATION_ERROR,
        CaseType.APPLICATION_ERROR,
        CaseType.UNKNOWN_RUNTIME_FAULT,
    ]:
        mgr = HypothesisManager(case_type=c_type, symptom="测试故障现象")
        assert 2 <= len(mgr.hypotheses) <= 6


def test_hypothesis_lifecycle_updates():
    """验证假设状态迁移：rule_out, strongly_support, confirm"""
    mgr = HypothesisManager(case_type=CaseType.ROBOT_EXECUTION_ERROR, symptom="机器人不走")
    assert not mgr.has_confirmed_hypothesis()
    assert not mgr.has_strongly_supported_hypothesis()

    # 排除 H1
    mgr.rule_out("H1", reason="PLC已成功接收报文", evidence="PLC_LOG_001")
    h1 = mgr.get_hypothesis("H1")
    assert h1.status == HypothesisStatus.RULED_OUT
    assert "PLC_LOG_001" in h1.contradicting_evidence

    # 强支持 H3
    mgr.strongly_support("H3", reason="机器人接口返回408超时", evidence="HTTP_TIMEOUT")
    h3 = mgr.get_hypothesis("H3")
    assert h3.status == HypothesisStatus.STRONGLY_SUPPORTED
    assert mgr.has_strongly_supported_hypothesis()
    assert mgr.get_top_hypothesis().hypothesis_id == "H3"

    # 确认 H3
    mgr.confirm("H3", reason="抓包证实机器人通信中断", evidence="PCAP_DATA")
    assert h3.status == HypothesisStatus.CONFIRMED
    assert mgr.has_confirmed_hypothesis()
