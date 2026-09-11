import pytest
from unittest.mock import patch
from pathlib import Path
from iro_agent.evaluation.models import EvalCase, EvalExpectation, EvalStatus
from iro_agent.evaluation.runner import EvaluationRunner


def test_eval_runner_records_infra_error_on_fatal_exception(tmp_path):
    """验证评测模式下遇到基础设施或LLM服务不可恢复异常时，严禁静默Fallback，必须如实记录INFRA_ERROR且得分为0"""
    case_file = tmp_path / "case_fatal.json"
    case_file.write_text(
        """
        {
            "case_id": "test_infra_fatal",
            "category": "plc",
            "input": {"symptom": "PLC通讯中断"},
            "expectation": {
                "acceptable_root_causes": ["plc_link_down"],
                "required_evidence_types": ["plc_log"]
            }
        }
        """,
        encoding="utf-8",
    )

    runner = EvaluationRunner(
        dataset_type="external",
        custom_path=str(tmp_path),
        output_dir=str(tmp_path / "runs"),
    )

    # 模拟底座或排查主流程抛出致命连接异常
    with patch("iro_agent.investigation.harness.InvestigationHarness.investigate", side_effect=ConnectionError("GLM API service unavailable")):
        summary = runner.run()

    assert summary.total_cases == 1
    res = summary.results[0]
    # 必须是 INFRA_ERROR，得分必须为 0.0
    assert res.status == EvalStatus.INFRA_ERROR
    assert res.final_score == 0.0
    assert "service unavailable" in res.stop_reason
    assert summary.passed_cases == 0


def test_eval_runner_fails_on_tool_failure_without_fake_pass(tmp_path):
    """验证当核心诊断工具调用失败时，禁止隐式切换至兜底逻辑伪造通过，必须如实判定为 FAIL"""
    case_file = tmp_path / "case_tool_fail.json"
    case_file.write_text(
        """
        {
            "case_id": "test_tool_fail",
            "category": "plc",
            "input": {"symptom": "PLC通讯中断"},
            "expectation": {
                "acceptable_root_causes": ["plc_link_down"],
                "required_evidence_types": ["plc_communication_log"]
            }
        }
        """,
        encoding="utf-8",
    )

    failing_tools = {
        "log_search": lambda **kwargs: {"error": "Connection timed out connecting to PLC gateway"},
    }

    runner = EvaluationRunner(
        dataset_type="external",
        custom_path=str(tmp_path),
        tool_handlers=failing_tools,
        output_dir=str(tmp_path / "runs"),
    )

    summary = runner.run()
    assert summary.total_cases == 1
    res = summary.results[0]
    # 核心工具崩溃且根因未命中，严禁伪装为 PASS
    assert res.status == EvalStatus.FAIL
    assert summary.passed_cases == 0

