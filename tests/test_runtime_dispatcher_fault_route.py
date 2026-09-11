import pytest
from unittest.mock import MagicMock
from iro_agent.runtime.dispatcher import RuntimeDispatcher
from iro_agent.runtime.models import RuntimeRoute
from iro_agent.investigation.models import (
    InvestigationReport,
    CaseType,
    HypothesisStatus,
)


def test_determine_route_fault_vs_fact():
    dispatcher = RuntimeDispatcher()

    # 典型故障报障 -> RUNTIME_FAULT
    route1 = dispatcher.determine_route("机器人不动了，帮我查一下")
    assert route1 == RuntimeRoute.RUNTIME_FAULT

    route2 = dispatcher.determine_route("PLC通讯超时，后端报408错误")
    assert route2 == RuntimeRoute.RUNTIME_FAULT

    route3 = dispatcher.determine_route("调度卡死了，任务一直停留在 WAITING")
    assert route3 == RuntimeRoute.RUNTIME_FAULT

    # 典型事实/定义查询 -> FACT_QUERY
    route4 = dispatcher.determine_route("task 表有几个状态字段？")
    assert route4 == RuntimeRoute.FACT_QUERY

    route5 = dispatcher.determine_route("当前发布的最新版本是多少？")
    assert route5 == RuntimeRoute.FACT_QUERY

    # 通用日常聊天 -> GENERAL_CHAT
    route6 = dispatcher.determine_route("你好")
    assert route6 == RuntimeRoute.GENERAL_CHAT


def test_dispatch_fault_routes_to_harness():
    mock_harness = MagicMock()
    mock_report = InvestigationReport(
        case_id="case_test_01",
        symptom="机器人不动了，帮我查一下",
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        root_cause="机器人回调超时，网络端口断开",
        final_status="CONVERGED",
        key_evidence=["[TIER_LOG] 发现 408 Request Timeout"],
        unknown_factors=["底盘实际物理开关"],
        recommended_actions=["检查机器人网口指示灯"],
    )
    mock_harness.investigate.return_value = mock_report

    dispatcher = RuntimeDispatcher(harness=mock_harness)

    result = dispatcher.dispatch("机器人不动了，帮我查一下")

    assert result.route == RuntimeRoute.RUNTIME_FAULT
    assert result.investigation_report is not None
    assert result.investigation_report.case_id == "case_test_01"
    assert "【核心排查结论】" in result.reply_text
    assert "机器人回调超时" in result.reply_text
    mock_harness.investigate.assert_called_once()


def test_dispatch_fact_query_does_not_call_harness():
    mock_harness = MagicMock()
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = "ordersys_dock_task 表共有 3 个状态字段: status, execute_status, sync_status。"

    dispatcher = RuntimeDispatcher(harness=mock_harness, glm_client=mock_glm)

    result = dispatcher.dispatch("task 表有几个状态字段？")

    assert result.route == RuntimeRoute.FACT_QUERY
    assert result.investigation_report is None
    assert "3 个状态字段" in result.reply_text
    # 严格断言：事实查询绝不调用排查 Harness！
    mock_harness.investigate.assert_not_called()
