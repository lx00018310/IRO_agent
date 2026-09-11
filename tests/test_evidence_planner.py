from iro_agent.investigation.models import CaseType
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner


def test_evidence_planner_ordering_and_tools():
    """验证规划出的排查步骤按动态优先级降序排列，且工具匹配故障场景"""
    mgr = HypothesisManager(case_type=CaseType.ROBOT_EXECUTION_ERROR, symptom="机器人未执行送餐")
    steps = EvidencePlanner.plan_steps(hypo_mgr=mgr, case_type=CaseType.ROBOT_EXECUTION_ERROR, symptom="机器人未执行送餐")

    assert len(steps) >= 2
    # 验证排序单调递减或相等
    for i in range(len(steps) - 1):
        assert steps[i].priority >= steps[i + 1].priority

    # 机器人故障应排查机器人日志或DB主任务
    tools = [s.tool for s in steps]
    assert "log_search" in tools or "db_query" in tools
