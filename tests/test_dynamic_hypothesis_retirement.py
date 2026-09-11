import pytest
from iro_agent.investigation.models import CaseType, Hypothesis, HypothesisStatus
from iro_agent.investigation.hypotheses import HypothesisManager


def test_hypothesis_dynamic_add_and_retire():
    h1 = Hypothesis(hypothesis_id="H1", description="初始假设1: 网络丢包")
    h2 = Hypothesis(hypothesis_id="H2", description="初始假设2: 配置错误")

    mgr = HypothesisManager(initial_hypotheses=[h1, h2])

    assert len(mgr.active_hypotheses) == 2
    assert len(mgr.retired_hypotheses) == 0

    # 1. 动态淘汰 H1
    mgr.retire_hypothesis("H1", reason="PING 延迟稳定在 1ms，无丢包", evidence="NET_PING_LOG")
    assert len(mgr.active_hypotheses) == 1
    assert len(mgr.retired_hypotheses) == 1
    assert mgr.get_hypothesis("H1").status == HypothesisStatus.RULED_OUT
    assert "NET_PING_LOG" in mgr.get_hypothesis("H1").contradicting_evidence

    # 2. 排查过程中动态追加全新假设 H3
    new_id = mgr.add_hypothesis(
        description="动态发现的新线索: 数据库死锁导致阻塞",
        related_flow_step="数据持久化",
        required_evidence=["DB_DEADLOCK_LOG"],
    )
    assert new_id == "H3"
    assert len(mgr.active_hypotheses) == 2
    assert len(mgr.hypotheses) == 3

    # 3. 动态修订 H2 的检验证据
    mgr.revise_hypothesis(
        hypothesis_id="H2",
        new_description="修正描述: 配置项超时时间被设为 0",
        new_required_evidence=["CONFIG_DUMP"],
    )
    h2_revised = mgr.get_hypothesis("H2")
    assert "设为 0" in h2_revised.description
    assert h2_revised.required_evidence == ["CONFIG_DUMP"]

    # 4. 确认新假设 H3 结案
    mgr.confirm("H3", reason="日志发现明显的 Deadlock found when trying to get lock", evidence="MYSQL_DEADLOCK_TRACE")
    assert mgr.has_confirmed_hypothesis()
    assert mgr.get_top_hypothesis().hypothesis_id == "H3"
