import pytest
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceTier,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evaluator import EvidenceEvaluator


def test_evaluator_does_not_mutate_hypothesis_manager():
    """验证 EvidenceEvaluator 绝不直接调用 hypo_mgr 修改假设状态"""
    h1 = Hypothesis(hypothesis_id="H1", description="数据库写入阻塞", status=HypothesisStatus.UNRESOLVED)
    h2 = Hypothesis(hypothesis_id="H2", description="机器人通信断开", status=HypothesisStatus.UNRESOLVED)
    mgr = HypothesisManager(initial_hypotheses=[h1, h2])

    step = InvestigationStep(
        step_id="step_1",
        hypothesis_ids=["H1", "H2"],
        evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
        evidence_type="task_log",
        tool="log_search",
        tool_args={"keyword": "error"},
        reason="检索错误日志",
    )

    # 包含严重 ERROR 堆栈的日志输出
    raw_output = [
        {"level": "ERROR", "msg": "Deadlock detected on table tasks, transaction aborted"},
        {"level": "ERROR", "msg": "Critical: Robot socket disconnect EOF"},
    ]

    eval_res = EvidenceEvaluator.evaluate_step(step, raw_output, mgr)

    # 1. 验证事实提取客观定性为 FACT
    assert eval_res.verdict == "FACT"
    assert "包含报错或异常堆栈" in eval_res.detail

    # 2. 关键断言：Evaluator 绝不擅自打标签或改变假设状态！
    assert len(eval_res.impacted_hypotheses) == 0
    assert mgr.get_hypothesis("H1").status == HypothesisStatus.UNRESOLVED
    assert mgr.get_hypothesis("H2").status == HypothesisStatus.UNRESOLVED

    # 3. 证据记录中不含先验因果绑定
    ev = EvidenceEvaluator.create_evidence_record(step, raw_output, eval_res)
    assert ev.supports == []
    assert ev.contradicts == []
    assert ev.normalized_fact == eval_res.detail
