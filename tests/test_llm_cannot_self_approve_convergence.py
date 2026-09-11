import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    CaseType,
)
from iro_agent.llm.glm_client import GlmClient


def test_llm_cannot_self_approve_convergence_without_evidence():
    """验证 LLM 试图在没有提供/采集任何客观证据时直接声明 CONVERGE，必被 Harness Guardrail 严格拦截"""
    mock_glm = MagicMock(spec=GlmClient)
    # 模拟大模型行为：
    # 1. 动态假设推演 (Dynamic Hypothesis Generation)
    # 2. 第 1 轮模型直接试图收敛（无证据）
    # 3. 第 2 轮模型再次试图收敛（连续 2 次无证据被 Guardrail 拦截并以 INSUFFICIENT_EVIDENCE 结案）
    mock_glm.complete_structured.side_effect = [
        """```json
[
  {"hypothesis_id": "H1", "description": "系统逻辑死锁", "related_flow_step": "调度", "required_evidence": ["log_search"]}
]
```""",
        """{
            "thought": "我觉得就是逻辑死锁，不需要查日志了，直接收敛",
            "decision": "CONVERGE",
            "reason": "主观臆断收敛"
        }""",
        """{
            "thought": "再次申请收敛",
            "decision": "CONVERGE",
            "reason": "依然没有证据"
        }""",
    ]

    harness = InvestigationHarness(
        planner_mode="llm",
        glm_client=mock_glm,
        tool_handlers={"log_search": lambda **kw: []},
    )

    report = harness.investigate(symptom="设备停滞")

    # 关键断言 1: Harness 绝不允许未经验证的收敛申请通过！
    assert report.final_status != "CONVERGED"
    assert report.final_status == "INSUFFICIENT_EVIDENCE"

    # 关键断言 2: stop_reason 包含安全防护拦截和证据不足标识
    assert "STOP_INSUFFICIENT_EVIDENCE" in report.stop_reason or "安全防护" in report.stop_reason
    assert report.confidence in ("Inconclusive", "Low")
