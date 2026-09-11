import pytest
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import CaseType, HypothesisStatus


def test_tool_timeout_produces_observability_gap():
    """验证当核心诊断工具调用超时或报错时，正确记录工具异常与观测缺口，不将错误等价于'无异常'"""
    mock_tools = {
        # PLC 工具超时模拟
        "log_search": lambda **kwargs: {"error": "Connection timed out connecting to PLC gateway after 5000ms"},
        "db_query": lambda **kwargs: [],
        "config_lookup": lambda query, limit=5: [],
        "version_current": lambda: {"version": "v1.2.0"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="PLC通信异常导致机器人未动作")

    assert report is not None
    # 验证证据列表中包含了工具异常或错误记录
    error_evidence = [e for e in report.evidence_records if e.is_error]
    assert error_evidence[0].error_type in ("tool_failure", "OBSERVABILITY_GAP")
    assert "timed out" in str(error_evidence[0].raw_summary).lower()

    # 验证不应该被认定为明确排除了故障，结论应带有证据不足或观测缺口特征
    assert report.confidence == "Inconclusive"
    assert "观测缺口" in report.primary_root_cause or "不足" in report.primary_root_cause
