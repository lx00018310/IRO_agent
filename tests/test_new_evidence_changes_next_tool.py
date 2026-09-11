import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import DecisionAction


def test_new_evidence_changes_next_tool_path():
    """验证新证据动态改变下一步工具决策"""
    mock_glm = MagicMock()
    # 模拟两轮 LLM 决策响应：
    # 轮次 1: 发现问题后决定先查日志
    # 轮次 2: 看到日志中的 PLC Connection refused 后，模型自主转向读取 PLC
    mock_glm.chat_completion.side_effect = [
        # Round 1 Planner Decision
        """```json
{
  "thought": "排查机器人停止，首先检索运行日志以发现最初异常",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "ERROR"},
  "reason": "排查初始异常日志"
}
```""",
        # Round 2 Planner Decision
        """```json
{
  "thought": "前序日志显示与 PLC 通信 Connection refused，说明问题出在 PLC 侧，立即转向读取 PLC 状态",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H2",
  "tool_name": "plc_read",
  "tool_arguments": {"address": "DB10.DBX0.0"},
  "reason": "排查 PLC 现场点位"
}
```""",
        # Round 3 Converge
        """```json
{
  "thought": "已证实 PLC 连接拒绝且点位异常，证据充分，主动收敛结案",
  "decision": "CONVERGE",
  "reason": "确认为 PLC 信号中断"
}
```"""
    ]

    mock_tools = {
        "log_search": MagicMock(return_value={"logs": ["[ERROR] Connection refused on 192.168.1.10:502"]}),
        "plc_read": MagicMock(return_value={"status": "OFFLINE", "address": "DB10.DBX0.0"}),
    }

    harness = InvestigationHarness(
        tool_handlers=mock_tools,
        planner_mode="llm",
        glm_client=mock_glm,
    )

    report = harness.investigate(symptom="机器人突然停机")

    # 验证工具被按动态推理顺序调用：log_search -> plc_read
    assert mock_tools["log_search"].called
    assert mock_tools["plc_read"].called
    assert len(report.investigation_trace) == 2
    assert report.investigation_trace[0].tool == "log_search"
    assert report.investigation_trace[1].tool == "plc_read"
