import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.models import CaseType, HypothesisStatus
from iro_agent.investigation.hypotheses import HypothesisManager, DynamicHypothesisGenerator


def test_dynamic_hypothesis_generation_from_llm():
    mock_glm = MagicMock()
    mock_glm.chat_completion.return_value = """
```json
[
  {
    "hypothesis_id": "H1",
    "description": "堆垛机激光测距传感器受到强反光干扰丢失位置",
    "related_flow_step": "堆垛机定位",
    "required_evidence": ["堆垛机硬件状态字", "激光测距点位值"]
  },
  {
    "hypothesis_id": "H2",
    "description": "WCS 下发的坐标超出货架物理边界触发软限位停机",
    "related_flow_step": "指令下发与范围校验",
    "required_evidence": ["WCS 任务日志", "限位报警记录"]
  },
  {
    "hypothesis_id": "H3",
    "description": "堆垛机变频器过载保护跳闸",
    "related_flow_step": "电气驱动",
    "required_evidence": ["变频器故障代码", "母线电压记录"]
  }
]
```
"""
    mgr = HypothesisManager(
        symptom="堆垛机行走到一半突然停住，无主控报警",
        glm_client=mock_glm,
    )

    # 验证由 LLM 动态推导生成，且数量和内容完全符合工况
    assert len(mgr.hypotheses) == 3
    assert mgr.hypotheses[0].hypothesis_id == "H1"
    assert "激光测距" in mgr.hypotheses[0].description
    assert mgr.hypotheses[1].hypothesis_id == "H2"
    assert "超出货架物理边界" in mgr.hypotheses[1].description
    assert mgr.hypotheses[2].hypothesis_id == "H3"
    assert "变频器过载" in mgr.hypotheses[2].description


def test_dynamic_hypothesis_fallback_when_llm_fails():
    mock_glm = MagicMock()
    # 模拟大模型报错或返回无效内容
    mock_glm.chat_completion.side_effect = Exception("LLM 服务暂时不可用")

    mgr = HypothesisManager(
        case_type=CaseType.ROBOT_EXECUTION_ERROR,
        symptom="机器人通信异常",
        glm_client=mock_glm,
    )

    # 验证触发确定性降级，绝不崩溃，生成 2~6 个基础假设
    assert 2 <= len(mgr.hypotheses) <= 6
    assert any("机器人" in h.description or "信号" in h.description for h in mgr.hypotheses)
