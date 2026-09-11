import pytest
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceTier,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evaluator import EvidenceEvaluator


def test_log_error_not_auto_root_cause_for_unrelated_hypothesis():
    """关键 Case: 当前假设为机器人通信故障，日志出现 ERROR database retry，严禁自动支持机器人假设"""
    h_robot = Hypothesis(
        hypothesis_id="H_robot",
        description="机器人通信断开或超时",
        status=HypothesisStatus.UNRESOLVED,
    )
    mgr = HypothesisManager(initial_hypotheses=[h_robot])

    step = InvestigationStep(
        step_id="step_log_db",
        hypothesis_ids=["H_robot"],
        evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        evidence_type="backend_log",
        tool="log_search",
        tool_args={"keyword": "database"},
        reason="检查日志中相关活动",
    )

    # 日志确实有 ERROR，但是是数据库连接重试
    tool_output = [
        {"level": "ERROR", "message": "database connection pool exhausted, retrying in 3s"}
    ]

    eval_res = EvidenceEvaluator.evaluate_step(step, tool_output, mgr)

    # Evaluator 仅客观记录发现日志报错
    assert eval_res.verdict == "FACT"
    assert "包含报错或异常堆栈" in eval_res.detail

    # 严禁将该报错当作对 H_robot 的支持或因果证实！
    assert mgr.get_hypothesis("H_robot").status == HypothesisStatus.UNRESOLVED
    assert "H_robot" not in eval_res.impacted_hypotheses

    ev_record = EvidenceEvaluator.create_evidence_record(step, tool_output, eval_res)
    assert "H_robot" not in ev_record.supports
    assert ev_record.supports == []
