import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from iro_agent.cli import cmd_investigate
from iro_agent.runtime.dispatcher import RuntimeDispatcher
from iro_agent.runtime.models import RuntimeRoute, DispatchResult
from iro_agent.investigation.models import InvestigationReport, CaseType


def test_cli_cmd_investigate(capsys):
    args = Namespace(symptom="机器人卡在转弯点无法移动", verbose=False)

    mock_report = InvestigationReport(
        case_id="case_cli_01",
        symptom=args.symptom,
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        root_cause="机器人急停按钮触发",
        final_status="CONVERGED",
        key_evidence=["[TIER_HARDWARE] E-Stop physical signal ACTIVE"],
        recommended_actions=["现场复位急停旋钮"],
    )

    with patch("iro_agent.cli.RuntimeDispatcher") as MockDispatcher:
        mock_instance = MagicMock()
        mock_instance.dispatch.return_value = DispatchResult(
            route=RuntimeRoute.RUNTIME_FAULT,
            reply_text="【核心排查结论】\n机器人急停按钮触发\n\n【关键事实依据】\n- E-Stop physical signal ACTIVE",
            investigation_report=mock_report,
        )
        MockDispatcher.return_value = mock_instance

        cmd_investigate(args)

        mock_instance.dispatch.assert_called_once()
        captured = capsys.readouterr()
        assert "【核心排查结论】" in captured.out
        assert "机器人急停按钮触发" in captured.out
