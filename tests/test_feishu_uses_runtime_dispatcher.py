import pytest
from unittest.mock import MagicMock
from iro_agent.gateway.feishu import FeishuGateway
from iro_agent.gateway.base import GatewayMessage
from iro_agent.runtime.dispatcher import RuntimeDispatcher
from iro_agent.runtime.models import RuntimeRoute, DispatchResult
from iro_agent.investigation.models import InvestigationReport, CaseType


def test_feishu_message_routes_through_dispatcher(tmp_path):
    mock_dispatcher = MagicMock(spec=RuntimeDispatcher)
    mock_report = InvestigationReport(
        case_id="case_feishu_01",
        symptom="PLC通信中断",
        case_type=CaseType.PLC_SIGNAL_ERROR,
        root_cause="PLC边界端口拒绝连接",
        final_status="CONVERGED",
        key_evidence=["[TIER_LOG] Connection refused on 192.168.1.10:502"],
        recommended_actions=["检查PLC供电与交换机接线"],
    )
    mock_dispatcher.dispatch.return_value = DispatchResult(
        route=RuntimeRoute.RUNTIME_FAULT,
        reply_text="【核心排查结论】\nPLC边界端口拒绝连接\n\n【关键事实依据】\n- Connection refused\n\n【建议下一步处置】\n- 检查PLC供电",
        investigation_report=mock_report,
    )

    db_file = tmp_path / "dedup.db"
    gateway = FeishuGateway(
        dispatcher=mock_dispatcher,
        dedup_db_path=str(db_file),
    )
    # mock 发送飞书消息
    gateway.send_message = MagicMock(return_value=True)

    msg = GatewayMessage(
        message_id="msg_101",
        chat_id="oc_test_chat",
        user_id="ou_test_user",
        text="PLC通信中断了，赶紧排查一下",
        event_id="evt_101",
    )

    # mock 添加 reaction，避免真实外联网络
    gateway.add_reaction = MagicMock(return_value=True)

    # 触发标准消息处理入口
    gateway.handle_message(msg)

    # 验证经过了 RuntimeDispatcher
    mock_dispatcher.dispatch.assert_called_once()
    args, kwargs = mock_dispatcher.dispatch.call_args
    assert "PLC通信中断" in kwargs.get("message", args[0] if args else "")

    # 验证最终通过 send_message 将排查报告发往飞书
    gateway.send_message.assert_called_once()
    _, send_kwargs = gateway.send_message.call_args
    assert "核心排查结论" in send_kwargs.get("text", "")
    assert "PLC边界端口拒绝连接" in send_kwargs.get("text", "")
