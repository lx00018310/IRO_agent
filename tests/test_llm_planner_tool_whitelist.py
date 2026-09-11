import pytest
from iro_agent.investigation.tool_registry import ToolRegistry, ToolSpec
from iro_agent.investigation.planner_validator import PlannerValidator
from iro_agent.investigation.models import PlannerDecision, DecisionAction, Hypothesis


def test_dangerous_tool_rejection():
    registry = ToolRegistry()
    validator = PlannerValidator(registry=registry)
    h1 = Hypothesis(hypothesis_id="H1", description="测试假设")

    # 尝试调用系统 shell 或修改指令
    decision = PlannerDecision(
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="cmd_shell",
        tool_arguments={"cmd": "rm -rf /"},
    )
    is_valid, err = validator.validate(decision, [h1])
    assert not is_valid
    assert "不在只读工具白名单中" in err


def test_database_write_prevention():
    registry = ToolRegistry()
    validator = PlannerValidator(registry=registry)
    h1 = Hypothesis(hypothesis_id="H1", description="测试假设")

    # 尝试在 db_query 中执行 DELETE / UPDATE
    bad_decisions = [
        PlannerDecision(
            decision=DecisionAction.EXECUTE_TOOL,
            target_hypothesis="H1",
            tool_name="db_query",
            tool_arguments={"sql": "DELETE FROM ordersys_dock_task WHERE id=1"},
        ),
        PlannerDecision(
            decision=DecisionAction.EXECUTE_TOOL,
            target_hypothesis="H1",
            tool_name="db_query",
            tool_arguments={"sql": "UPDATE config_item SET val='bad'"},
        ),
        PlannerDecision(
            decision=DecisionAction.EXECUTE_TOOL,
            target_hypothesis="H1",
            tool_name="db_query",
            tool_arguments={"sql": "DROP TABLE sys_log"},
        ),
    ]

    for dec in bad_decisions:
        is_valid, err = validator.validate(dec, [h1])
        assert not is_valid
        assert "仅允许只读查询操作" in err or "检测到数据库写/结构变更关键字" in err


def test_plc_write_prevention():
    registry = ToolRegistry()
    validator = PlannerValidator(registry=registry)
    h1 = Hypothesis(hypothesis_id="H1", description="测试假设")

    # 尝试写入 PLC
    decision = PlannerDecision(
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="plc_read",
        tool_arguments={"address": "DB100.DBX0.0", "write_value": 1},
    )
    is_valid, err = validator.validate(decision, [h1])
    assert not is_valid
    assert "禁止传入写入值" in err


def test_robot_control_prevention():
    registry = ToolRegistry()
    validator = PlannerValidator(registry=registry)
    h1 = Hypothesis(hypothesis_id="H1", description="测试假设")

    # 尝试控制机器人运动
    decision = PlannerDecision(
        decision=DecisionAction.EXECUTE_TOOL,
        target_hypothesis="H1",
        tool_name="robot_query",
        tool_arguments={"action": "move_to", "target": "point_A"},
    )
    is_valid, err = validator.validate(decision, [h1])
    assert not is_valid
    assert "禁止发送任何运动或复位控制指令" in err


def test_non_readonly_tool_registration_rejected():
    registry = ToolRegistry()
    with pytest.raises(PermissionError, match="安全违规拦截"):
        registry.register(ToolSpec(
            name="write_tool",
            description="危险写工具",
            risk_level="WRITE_RISK",
        ))
