import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness


def test_same_symptom_different_evidence_branching():
    """验证相同 Symptom，因不同环境证据产生不同排查路径分支"""
    symptom = "月台出库任务停滞不前"

    # 情况 A: 第一步日志发现 DB 锁等待 -> 第二步转向 db_query
    glm_case_a = MagicMock()
    glm_case_a.chat_completion.side_effect = [
        # Dynamic Hypothesis Generation
        """```json
[
  {"hypothesis_id": "H1", "description": "出库主任务阻塞", "related_flow_step": "出库调度", "required_evidence": ["log_search"]},
  {"hypothesis_id": "H2", "description": "数据库行锁冲突", "related_flow_step": "数据库事务", "required_evidence": ["db_query"]}
]
```""",
        """```json
{"thought": "先查日志", "decision": "EXECUTE_TOOL", "target_hypothesis": "H1", "tool_name": "log_search", "tool_arguments": {"keyword": "dock_task"}, "reason": "看日志"}
```""",
        """```json
{"thought": "日志显示 Lock wait timeout，转向查数据库死锁与事务", "decision": "EXECUTE_TOOL", "target_hypothesis": "H2", "tool_name": "db_query", "tool_arguments": {"sql": "SELECT * FROM ordersys_dock_task WHERE status='WAITING'"}, "reason": "查DB"}
```""",
        """```json
{"thought": "证实为 DB 行锁阻塞", "decision": "CONVERGE", "reason": "数据库死锁"}
```"""
    ]
    tools_a = {
        "log_search": MagicMock(return_value={"logs": ["[WARN] Lock wait timeout exceeded on ordersys_dock_task"]}),
        "db_query": MagicMock(return_value={"rows": [{"id": 101, "status": "WAITING"}]}),
        "robot_query": MagicMock(),
    }
    harness_a = InvestigationHarness(tool_handlers=tools_a, planner_mode="llm", glm_client=glm_case_a)
    report_a = harness_a.investigate(symptom)

    assert tools_a["log_search"].called
    assert tools_a["db_query"].called
    assert not tools_a["robot_query"].called
    assert [s.tool for s in report_a.investigation_trace] == ["log_search", "db_query"]

    # 情况 B: 第一步日志发现机器人未就绪 -> 第二步转向 robot_query
    glm_case_b = MagicMock()
    glm_case_b.chat_completion.side_effect = [
        # Dynamic Hypothesis Generation
        """```json
[
  {"hypothesis_id": "H1", "description": "出库主任务阻塞", "related_flow_step": "出库调度", "required_evidence": ["log_search"]},
  {"hypothesis_id": "H3", "description": "机器人硬件报警未就绪", "related_flow_step": "机器人执行", "required_evidence": ["robot_query"]}
]
```""",
        """```json
{"thought": "先查日志", "decision": "EXECUTE_TOOL", "target_hypothesis": "H1", "tool_name": "log_search", "tool_arguments": {"keyword": "dock_task"}, "reason": "看日志"}
```""",
        """```json
{"thought": "日志显示 Robot not ready，转向查机器人状态与报警", "decision": "EXECUTE_TOOL", "target_hypothesis": "H3", "tool_name": "robot_query", "tool_arguments": {"query_type": "alarm"}, "reason": "查机器人"}
```""",
        """```json
{"thought": "证实机器人处于急停状态", "decision": "CONVERGE", "reason": "机器人急停"}
```"""
    ]
    tools_b = {
        "log_search": MagicMock(return_value={"logs": ["[ERROR] Robot arm returned 408 Timeout: NOT_READY"]}),
        "db_query": MagicMock(),
        "robot_query": MagicMock(return_value={"alarm": "E-STOP_TRIGGERED"}),
    }
    harness_b = InvestigationHarness(tool_handlers=tools_b, planner_mode="llm", glm_client=glm_case_b)
    report_b = harness_b.investigate(symptom)

    assert tools_b["log_search"].called
    assert tools_b["robot_query"].called
    assert not tools_b["db_query"].called
    assert [s.tool for s in report_b.investigation_trace] == ["log_search", "robot_query"]
