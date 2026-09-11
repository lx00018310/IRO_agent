import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisStatus,
    HypothesisAction,
    HypothesisUpdate,
    PlannerDecision,
    DecisionAction,
)
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.harness import InvestigationHarness


def test_planner_can_dynamically_add_hypothesis():
    mgr = HypothesisManager(
        initial_hypotheses=[
            Hypothesis(hypothesis_id="H1", description="初始假设1"),
            Hypothesis(hypothesis_id="H2", description="初始假设2"),
        ]
    )

    updates = [
        HypothesisUpdate(
            action=HypothesisAction.ADD,
            statement="工控机系统时间发生漂移导致日志时间戳不一致",
            confidence=0.45,
            evidence_ids=[],
            reason="排查日志发现时间戳超前",
        )
    ]

    applied = mgr.apply_updates(updates)
    assert len(applied) == 1
    assert applied[0].startswith("ADD:")

    new_h_id = applied[0].split(":")[1]
    new_h = mgr.get_hypothesis(new_h_id)
    assert new_h is not None
    assert "时间发生漂移" in new_h.description
    assert new_h.status == HypothesisStatus.UNRESOLVED
    assert len(mgr.hypotheses) == 3


def test_harness_integration_planner_adds_hypothesis():
    """验证在真实排查主循环中，LLM Planner 提出 ADD 后 Harness 能够动态扩充假设空间"""
    mock_glm = MagicMock()
    # 动态假设生成 + 第一轮规划(ADD并查配置) + 第二轮收敛
    mock_glm.chat_completion.side_effect = [
        # Round 0: 动态假设
        """```json
[{"hypothesis_id": "H1", "description": "调度通信中断", "related_flow_step": "通信", "required_evidence": ["log_search"]}]
```""",
        # Round 1: Planner ADD H2 并查 config
        """```json
{
  "thought": "通信日志正常，推测可能是现场鉴权配置漂移，新增假设H2并查配置",
  "hypothesis_updates": [
    {
      "action": "ADD",
      "statement": "鉴权服务Token已失效或时钟漂移",
      "confidence": 0.5,
      "evidence_ids": [],
      "reason": "通信握手返回401"
    }
  ],
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "H1",
  "tool_name": "config_lookup",
  "tool_arguments": {"query": "auth_token"},
  "reason": "查鉴权配置"
}
```""",
        # Round 2: 收敛
        """```json
{
  "thought": "配置查明，收敛",
  "decision": "CONVERGE",
  "reason": "收敛"
}
```"""
    ]

    tools = {
        "log_search": lambda **kw: {"logs": ["401 unauthorized"]},
        "config_lookup": lambda **kw: {"configs": ["token_expired=true"]},
    }

    harness = InvestigationHarness(
        tool_handlers=tools,
        planner_mode="llm",
        glm_client=mock_glm,
    )

    report = harness.investigate("调度任务报401错误")
    # 验证最终报告中的假设集合包含动态 ADD 的假设
    assert any("时钟漂移" in h.description or "鉴权服务Token" in h.description for h in report.hypotheses)
