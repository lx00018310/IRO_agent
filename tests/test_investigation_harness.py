from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import CaseType


def test_harness_backend_error_case():
    """测试场景1: 后端报错异常，通过日志快速收敛定位根因"""
    mock_tools = {
        "log_search": lambda **kwargs: [{"level": "ERROR", "message": "NullPointerException at DockTaskService.java:42"}],
        "db_query": lambda **kwargs: [],
        "config_lookup": lambda query, limit=5: [],
        "version_current": lambda: {"version": "v1.2.0"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="后端服务报错崩溃，报NullPointerException")

    assert report.case_type == CaseType.APPLICATION_ERROR
    assert report.primary_root_cause is not None
    assert len(report.key_evidence) > 0
    human_ans = harness.format_human_response(report)
    assert "**核心结论**" in human_ans
    assert "**关键依据**" in human_ans


def test_harness_robot_stalled_case():
    """测试场景2: 机器人不走，排查机器人调度与任务生成状态"""
    mock_tools = {
        "log_search": lambda **kwargs: [{"level": "WARN", "message": "Robot HTTP 408 timeout connecting to AGV controller"}],
        "db_query": lambda **kwargs: [{"id": 101, "status": "CREATED", "slot_code": "DOCK_01"}],
        "config_lookup": lambda query, limit=5: [],
        "version_current": lambda: {"version": "v1.2.0"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="PLC已经发P2C，为什么机器人不走？")

    assert report.case_type in (CaseType.ROBOT_EXECUTION_ERROR, CaseType.PLC_SIGNAL_ERROR)
    assert len(report.investigation_trace) > 0


def test_harness_digital_evidence_normal_triggers_physical_checklist():
    """测试场景3: 所有数字日志与数据表均无任何异常，自动升级现场硬件物理排查清单"""
    mock_tools = {
        "log_search": lambda **kwargs: [],
        "db_query": lambda **kwargs: [{"id": 1, "status": "NORMAL"}],
        "config_lookup": lambda query, limit=5: [],
        "version_current": lambda: {"version": "v1.2.0"},
    }

    harness = InvestigationHarness(tool_handlers=mock_tools)
    report = harness.investigate(symptom="现场上车小车不动，但系统无任何报错")

    assert len(report.physical_escalation_checklist) >= 3
    human_ans = harness.format_human_response(report)
    assert "物理排查建议" in human_ans
    assert "急停" in human_ans or "光电" in human_ans
