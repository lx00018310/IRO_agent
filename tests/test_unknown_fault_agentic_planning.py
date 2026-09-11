import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness


def test_unknown_fault_agentic_planning_and_convergence():
    """验证面对全新未知工况，LLM 依然能自主规划工具并优雅收敛"""
    mock_glm = MagicMock()
    # 模拟面对一个完全没有在任何规则库里出现过的新奇异常
    mock_glm.chat_completion.side_effect = [
        # Round 0 Dynamic Hypothesis Generation
        """```json
[
  {"hypothesis_id": "H1", "description": "视觉相机失焦与曝光异常", "related_flow_step": "视觉分拣", "required_evidence": ["log_search"]}
]
```""",
        # LLM Planner Step 1
        """```json
{
  "thought": "未知异常：'托盘在视觉分拣工位反光失焦导致传送带急停'。首先核查最近的视觉日志",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "log_search",
  "tool_arguments": {"keyword": "camera_focus"},
  "reason": "排查工业相机日志"
}
```""",
        # LLM Planner Step 2
        """```json
{
  "thought": "视觉日志显示 exposure overflow，且当前数字系统无代码异常，判断为光源物理遮光罩松动，建议升级现场物理检查",
  "decision": "ESCALATE_PHYSICAL",
  "reason": "工业相机曝光过载，需现场检查物理遮光罩与补光灯"
}
```"""
    ]

    mock_tools = {
        "log_search": MagicMock(return_value={"logs": ["[WARN] Camera focus loss: exposure overflow (val=9999)"]}),
    }

    harness = InvestigationHarness(
        tool_handlers=mock_tools,
        planner_mode="llm",
        glm_client=mock_glm,
    )

    report = harness.investigate(symptom="托盘在视觉分拣工位反光失焦导致传送带急停")

    # 验证排查不仅未中断，而且准确根据模型判断完成了物理升级判定
    assert len(report.investigation_trace) == 1
    assert report.investigation_trace[0].tool == "log_search"
    assert report.physical_escalation_checklist or "物理" in report.primary_root_cause
