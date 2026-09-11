import pytest
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import CaseType


def test_no_false_physical_escalation_when_tool_fails():
    """验证当排查工具失败出现观测缺口时，严禁误判为现场物理故障，严禁升级物理排查清单"""
    mock_tools = {
        "log_search": lambda **kwargs: {"error": "Failed to read log directory: Permission denied"},
        "db_query": lambda **kwargs: {"error": "MySQL server has gone away"},
        "config_lookup": lambda query, limit=5: [],
        "version_current": lambda: {"version": "UNKNOWN"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="小车在产线静止不动")

    # 验证物理排查清单没有被错误生成
    assert len(report.physical_escalation_checklist) == 0

    # 结论应指出观测断链或证据不足，而非断定为硬件损坏
    assert "物理带外状态异常" not in report.primary_root_cause
    assert "观测缺口" in report.primary_root_cause or "不足" in report.primary_root_cause


def test_valid_physical_escalation_only_when_digital_complete_and_normal():
    """验证只有在数字事实完整核查且均处于正常无异常状态时，方可升级为物理带外排查"""
    mock_tools = {
        # 日志正常无报错
        "log_search": lambda **kwargs: [],
        # 数据库状态正常
        "db_query": lambda **kwargs: [{"id": 1, "task_status": "NORMAL_FINISHED"}],
        "config_lookup": lambda query, limit=5: [{"key": "timeout", "value": "30"}],
        "version_current": lambda: {"version": "v1.2.0"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="上车小车不动，但系统无任何报错")

    # 此时数字各端均健康正常，符合物理升级条件
    assert len(report.physical_escalation_checklist) > 0
    assert "物理带外状态异常" in report.primary_root_cause
