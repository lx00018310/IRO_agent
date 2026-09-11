import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from iro_agent.runtime.dispatcher import RuntimeDispatcher
from iro_agent.runtime.models import RuntimeRoute, DispatchResult
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import (
    InvestigationReport,
    CaseType,
    HypothesisStatus,
    Hypothesis,
)
from iro_agent.evaluation.runner import EvaluationRunner
from iro_agent.evaluation.models import EvalStatus


def _create_mock_report(case_id: str = "test_case", primary_cause: str = "PLC communication timeout"):
    return InvestigationReport(
        case_id=case_id,
        symptom="PLC信号未上报",
        case_type=CaseType.PLC_SIGNAL_ERROR,
        primary_root_cause=primary_cause,
        confidence="High",
        stop_reason="CONFIRMED_CAUSE",
        investigation_trace=[],
        hypotheses=[
            Hypothesis(
                hypothesis_id="H1",
                description="PLC communication link is down",
                status=HypothesisStatus.CONFIRMED,
                confidence="High",
            )
        ],
    )


def test_eval_runner_routes_through_runtime_dispatcher(tmp_path):
    """验证 EvaluationRunner 默认使用 RuntimeDispatcher 进行统一分发执行"""
    case_file = tmp_path / "case_mock.json"
    case_file.write_text(
        """
        {
            "case_id": "case_runtime_align",
            "category": "plc",
            "input": {"symptom": "PLC信号未上报"},
            "expectation": {
                "acceptable_root_causes": ["PLC communication timeout"],
                "required_evidence_types": []
            }
        }
        """,
        encoding="utf-8",
    )

    mock_report = _create_mock_report(case_id="case_runtime_align")

    with patch.object(RuntimeDispatcher, "dispatch") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            route=RuntimeRoute.RUNTIME_FAULT,
            reply_text="【排查完成】PLC通信超时故障已确认",
            investigation_report=mock_report,
            metadata={"case_id": "case_runtime_align", "case_type": "plc_signal_error"},
        )

        runner = EvaluationRunner(
            dataset_type="external",
            custom_path=str(tmp_path),
            output_dir=str(tmp_path / "runs"),
        )
        summary = runner.run()

        # 校验必须调用了 RuntimeDispatcher.dispatch，且指定了 RUNTIME_FAULT
        assert mock_dispatch.called
        call_kwargs = mock_dispatch.call_args
        assert call_kwargs.kwargs["message"] == "PLC信号未上报"
        assert call_kwargs.kwargs["context"]["force_route"] == RuntimeRoute.RUNTIME_FAULT

        assert summary.total_cases == 1
        res = summary.results[0]
        assert res.case_id == "case_runtime_align"
        assert res.status == EvalStatus.PASS
        assert res.final_answer == "PLC communication timeout"


def test_eval_runner_supports_injected_dispatcher(tmp_path):
    """验证 EvaluationRunner 支持显式注入自定义或特定配置的 RuntimeDispatcher"""
    case_file = tmp_path / "case_injected.json"
    case_file.write_text(
        """
        {
            "case_id": "case_injected",
            "category": "robot",
            "input": {"symptom": "机器人执行中断"},
            "expectation": {
                "acceptable_root_causes": ["robot_arm_collision"],
                "required_evidence_types": []
            }
        }
        """,
        encoding="utf-8",
    )

    custom_dispatcher = MagicMock(spec=RuntimeDispatcher)
    mock_report = _create_mock_report(case_id="case_injected", primary_cause="robot_arm_collision")
    custom_dispatcher.dispatch.return_value = DispatchResult(
        route=RuntimeRoute.RUNTIME_FAULT,
        reply_text="机器人机械臂发生干涉碰撞",
        investigation_report=mock_report,
    )

    runner = EvaluationRunner(
        dataset_type="external",
        custom_path=str(tmp_path),
        output_dir=str(tmp_path / "runs"),
        dispatcher=custom_dispatcher,
    )

    summary = runner.run()
    assert custom_dispatcher.dispatch.called
    assert summary.passed_cases == 1


def test_eval_runner_handles_dispatcher_infra_failure(tmp_path):
    """验证当 RuntimeDispatcher 抛出基础设施异常时，EvaluationRunner 记录 INFRA_ERROR 而非吞掉或假通过"""
    case_file = tmp_path / "case_infra_err.json"
    case_file.write_text(
        """
        {
            "case_id": "case_infra_err",
            "category": "plc",
            "input": {"symptom": "通讯中断"},
            "expectation": {
                "acceptable_root_causes": ["link_down"],
                "required_evidence_types": []
            }
        }
        """,
        encoding="utf-8",
    )

    custom_dispatcher = MagicMock(spec=RuntimeDispatcher)
    custom_dispatcher.dispatch.side_effect = RuntimeError("Dispatcher upstream bridge timeout")

    runner = EvaluationRunner(
        dataset_type="external",
        custom_path=str(tmp_path),
        output_dir=str(tmp_path / "runs"),
        dispatcher=custom_dispatcher,
    )

    summary = runner.run()
    assert summary.error_cases == 1
    assert summary.results[0].status == EvalStatus.INFRA_ERROR
    assert "Dispatcher upstream bridge timeout" in summary.results[0].stop_reason


def test_runtime_eval_end_to_end_consistency(tmp_path):
    """端到端一致性校验：直接调用 RuntimeDispatcher 与经由 EvaluationRunner 驱动 InvestigationHarness 产物完全一致"""
    mock_tools = {
        "log_search": lambda **kwargs: {"found": True, "entries": ["PLC connection reset by peer"]},
        "plc_reader": lambda **kwargs: {"connected": False, "register_val": 0},
    }

    # 1. 直接调用生产运行时分发器
    harness_prod = InvestigationHarness(tool_handlers=mock_tools, planner_mode="deterministic")
    dispatcher_prod = RuntimeDispatcher(harness=harness_prod)
    dispatch_prod_res = dispatcher_prod.dispatch(
        message="PLC已经发了P2C信号，为什么机器人不动？",
        context={"force_route": RuntimeRoute.RUNTIME_FAULT},
    )

    # 2. 评测运行器驱动（使用包含观察缺失/证据不足容忍度的用例期望）
    case_file = tmp_path / "case_consistency.json"
    case_file.write_text(
        """
        {
            "case_id": "case_consistency_01",
            "category": "plc",
            "input": {"symptom": "PLC已经发了P2C信号，为什么机器人不动？"},
            "expectation": {
                "acceptable_root_causes": ["insufficient_evidence", "证据不足", "观察缺失", "未完成取证"],
                "required_evidence_types": []
            }
        }
        """,
        encoding="utf-8",
    )

    harness_eval = InvestigationHarness(tool_handlers=mock_tools, planner_mode="deterministic")
    dispatcher_eval = RuntimeDispatcher(harness=harness_eval)
    runner = EvaluationRunner(
        dataset_type="external",
        custom_path=str(tmp_path),
        output_dir=str(tmp_path / "runs"),
        dispatcher=dispatcher_eval,
    )
    summary = runner.run()

    # 验证排查结果对象的一致性
    assert dispatch_prod_res.investigation_report is not None
    eval_report = summary.results[0]
    assert dispatch_prod_res.route == RuntimeRoute.RUNTIME_FAULT
    assert dispatch_prod_res.investigation_report.case_type == CaseType.PLC_SIGNAL_ERROR
    assert eval_report.case_id == "case_consistency_01"
    assert eval_report.status == EvalStatus.PASS
    # 核心字段完全一致
    assert eval_report.final_answer == dispatch_prod_res.investigation_report.primary_root_cause
    assert eval_report.stop_reason == dispatch_prod_res.investigation_report.stop_reason
    assert eval_report.tool_call_count == len(dispatch_prod_res.investigation_report.investigation_trace)
