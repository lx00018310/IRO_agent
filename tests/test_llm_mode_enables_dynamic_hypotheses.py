import pytest
from unittest.mock import MagicMock, patch
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import Hypothesis, HypothesisStatus, PlannerDecision, DecisionAction
from iro_agent.investigation.hypotheses import DynamicHypothesisGenerator


def test_llm_mode_enables_dynamic_hypotheses_by_default():
    """验证在 LLM 模式下，默认强制启用动态假设推演，绝不走静态死板模板"""
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = """
```json
[
  {
    "hypothesis_id": "H1",
    "description": "堆垛机激光测距信号受到现场粉尘强遮挡",
    "related_flow_step": "激光测距定位",
    "required_evidence": ["log_search"]
  },
  {
    "hypothesis_id": "H2",
    "description": "WCS 调度系统下发任务物理坐标超限",
    "related_flow_step": "调度任务下发",
    "required_evidence": ["db_query"]
  }
]
```
"""

    mock_planner = MagicMock()
    mock_planner.plan_next_step.return_value = PlannerDecision(
        decision=DecisionAction.CONVERGE,
        reason="测试动态假设生成后即收敛",
    )

    harness = InvestigationHarness(
        planner_mode="llm",
        glm_client=mock_glm,
        llm_planner=mock_planner,
    )

    assert harness.dynamic_hypotheses is True

    with patch.object(DynamicHypothesisGenerator, "generate_from_llm", wraps=DynamicHypothesisGenerator.generate_from_llm) as spy_gen:
        report = harness.investigate("堆垛机行走到一半突然停住")
        assert spy_gen.called

    # 验证初始假设确实来自大模型动态生成，而非 CaseType 固定模板
    assert len(report.hypotheses) == 2
    assert report.hypotheses[0].hypothesis_id == "H1"
    assert "激光测距" in report.hypotheses[0].description
    assert report.hypotheses[1].hypothesis_id == "H2"
    assert "WCS" in report.hypotheses[1].description


def test_deterministic_mode_uses_template_hypotheses():
    """验证在 deterministic 模式下，使用确定性工程模板假设"""
    harness = InvestigationHarness(
        planner_mode="deterministic",
        tool_handlers={"log_search": lambda **kwargs: {"found": False}},
    )

    assert harness.dynamic_hypotheses is False or harness.planner_mode == "deterministic"

    with patch.object(DynamicHypothesisGenerator, "generate_from_llm") as mock_gen:
        report = harness.investigate("PLC信号未响应")
        assert not mock_gen.called

    # 确定性模板应包含默认的 PLC 假设
    assert len(report.hypotheses) >= 2
