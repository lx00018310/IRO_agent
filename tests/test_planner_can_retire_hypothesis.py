import pytest
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisStatus,
    HypothesisAction,
    HypothesisUpdate,
)
from iro_agent.investigation.hypotheses import HypothesisManager


def test_planner_can_retire_hypothesis():
    mgr = HypothesisManager(
        initial_hypotheses=[
            Hypothesis(hypothesis_id="H1", description="网络物理层断开"),
            Hypothesis(hypothesis_id="H2", description="PLC寄存器状态错误"),
        ]
    )

    updates = [
        HypothesisUpdate(
            action=HypothesisAction.RETIRE,
            hypothesis_id="H1",
            reason="交换机端口Link正常且Ping网关延迟<1ms，彻底排除网络物理中断",
        )
    ]

    applied = mgr.apply_updates(updates)
    assert "RETIRE:H1" in applied

    h1 = mgr.get_hypothesis("H1")
    assert h1.status == HypothesisStatus.RULED_OUT
    assert h1 in mgr.retired_hypotheses
    assert h1 not in mgr.active_hypotheses
