import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.hypotheses import DynamicHypothesisGenerator
from iro_agent.llm.glm_client import GlmClient


def test_dynamic_hypothesis_generator_has_no_tool_loop():
    """断言 DynamicHypothesisGenerator 绝不进入多轮工具循环，不注入全局旧提示词，不传递 tools"""
    mock_glm = MagicMock(spec=GlmClient)
    mock_glm.complete_structured.return_value = """[
      {
        "hypothesis_id": "H1",
        "description": "PLC 端口握手超时",
        "related_flow_step": "PLC 通信",
        "required_evidence": ["PLC 日志"]
      },
      {
        "hypothesis_id": "H2",
        "description": "数据库任务处于锁表状态",
        "related_flow_step": "数据持久化",
        "required_evidence": ["锁表检查"]
      }
    ]"""

    hypos = DynamicHypothesisGenerator.generate_from_llm(
        symptom="小车失联",
        flows=[],
        glm_client=mock_glm,
    )

    # 1. 验证调用了 complete_structured，而不是 chat_completion
    assert mock_glm.complete_structured.called
    assert not mock_glm.chat_completion.called

    # 2. 验证 tools 为空或 None
    call_kwargs = mock_glm.complete_structured.call_args.kwargs
    tools_val = call_kwargs.get("tools", None)
    assert tools_val is None or tools_val == []

    # 3. 验证未混入旧 SYSTEM_PROMPT
    sys_prompt = call_kwargs.get("system_prompt", "")
    assert "你是工业现场只读智能诊断助手 IRO_agent" not in sys_prompt

    # 4. 成功解析假设
    assert hypos is not None
    assert len(hypos) == 2
    assert hypos[0].hypothesis_id == "H1"
