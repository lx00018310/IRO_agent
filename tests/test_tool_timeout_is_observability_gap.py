import pytest
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceTier,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evaluator import EvidenceEvaluator


def test_tool_timeout_extracted_as_observability_gap():
    """验证工具超时被准确提取为 OBSERVABILITY_GAP，且不误判假设"""
    h1 = Hypothesis(hypothesis_id="H1", description="PLC 通信服务异常")
    mgr = HypothesisManager(initial_hypotheses=[h1])

    step = InvestigationStep(
        step_id="step_1",
        hypothesis_ids=["H1"],
        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
        evidence_type="plc_log",
        tool="log_search",
        tool_args={"keyword": "PLC"},
        reason="查PLC日志",
    )

    # 模拟工具返回连接超时错误
    tool_timeout_output = {"error": "Connection timed out after 5000ms connecting to PLC gateway"}

    # 1. 验证事实提取阶段
    is_error, err_type, summary = EvidenceEvaluator.extract_fact(step, tool_timeout_output)
    assert is_error is True
    assert err_type == "OBSERVABILITY_GAP"
    assert "OBSERVABILITY_GAP" in summary

    # 2. 验证因果裁决阶段
    eval_res = EvidenceEvaluator.judge_causality(
        step=step,
        tool_output=tool_timeout_output,
        is_error=is_error,
        error_type=err_type,
        fact_summary=summary,
        hypo_mgr=mgr,
    )
    assert eval_res.verdict == "OBSERVABILITY_GAP"
    # 关键断言：绝对不能推翻假设 H1，假设状态必须保持为 UNRESOLVED
    assert mgr.get_hypothesis("H1").status == HypothesisStatus.UNRESOLVED

    # 3. 验证结构化证据记录
    record = EvidenceEvaluator.create_evidence_record(step, tool_timeout_output, eval_res)
    assert record.is_error is True
    assert record.error_type == "OBSERVABILITY_GAP"
    assert record.reliability == 0.0
    assert len(record.contradicts) == 0
