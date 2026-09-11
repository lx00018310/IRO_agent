import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.llm.glm_client import GlmClient


def test_llm_cannot_self_approve_physical_escalation():
    """断言 LLM Planner 提议物理升级时，若数字证据未覆盖充分，必须被 Harness 拦截，严禁 self-approve"""
    mock_glm = MagicMock(spec=GlmClient)
    # 第一步：动态假设
    # 第二步：模型试图直接宣称物理升级（没有任何数字日志和业务状态证据）
    mock_glm.complete_structured.side_effect = [
        """[
            {"hypothesis_id": "H1", "description": "光电开关脏污", "related_flow_step": "感应", "required_evidence": ["传感器"]}
        ]""",
        """{
            "thought": "我觉得是硬件坏了，直接升级物理排查",
            "decision": "ESCALATE_PHYSICAL",
            "reason": "高度怀疑光电开关脏污"
        }"""
    ]

    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    report = harness.investigate(symptom="托盘未到位")

    # 关键断言：Harness 拦截了未经充分数字验证的物理升级！
    assert report.physical_escalation_required is False
    assert report.final_status != "PHYSICAL_ESCALATION"
    assert report.final_status == "INSUFFICIENT_EVIDENCE"
    assert len(report.physical_escalation_checklist) == 0
