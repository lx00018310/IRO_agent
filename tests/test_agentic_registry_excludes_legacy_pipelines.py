import pytest
from unittest.mock import MagicMock
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.tool_registry import ToolRegistry
from iro_agent.llm.glm_client import GlmClient


def test_agentic_registry_excludes_legacy_pipelines():
    """断言 LLM Planner Tool Catalog 中不存在 diagnostic_pipeline 和 investigation_pipeline"""
    # 1. 验证纯注册表默认不包含 legacy pipelines
    agentic_registry = ToolRegistry(include_legacy_pipelines=False)
    assert "diagnostic_pipeline" not in agentic_registry.list_tool_names()
    assert "investigation_pipeline" not in agentic_registry.list_tool_names()

    # 2. 验证 Harness 在 llm 模式下初始化的工具注册表与 prompt 描述
    mock_glm = MagicMock(spec=GlmClient)
    harness = InvestigationHarness(planner_mode="llm", glm_client=mock_glm)

    tool_names = harness.tool_registry.list_tool_names()
    assert "diagnostic_pipeline" not in tool_names
    assert "investigation_pipeline" not in tool_names

    prompt_desc = harness.tool_registry.get_prompt_description()
    assert "diagnostic_pipeline" not in prompt_desc
    assert "investigation_pipeline" not in prompt_desc
