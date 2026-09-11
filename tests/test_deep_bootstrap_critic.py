import pytest
from unittest.mock import patch
from pathlib import Path
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.config import GlmConfig
from iro_agent.llm.glm_client import GlmClient


def test_critic_pass_identifies_unknowns_and_weaknesses(tmp_path):
    """验证 Critic Pass 能够有效审查知识体系并输出未知盲区"""
    glm_cfg = GlmConfig(api_key="mock-key-for-critic", model="glm-5.3-flash")
    synthesizer = KnowledgeSynthesizer(glm_cfg=glm_cfg)

    tree_res = TreeScanResult(
        project_root=str(tmp_path),
        top_level_modules=["core", "robot"],
        primary_language="java",
    )
    schema_res = SchemaScanResult(connected=False)
    code_res = CodeScanResult()

    critic_mock = {
        "confirmed_facts": ["核心架构为分布式架构"],
        "strongly_inferred_facts": ["robot 模块负责控制通信"],
        "weak_inferences": ["假定心跳周期为 1000ms"],
        "unknown_areas": ["机器人底层防碰撞光栅信号", "PLC 急停物理硬接线"],
        "contradictions": [],
    }

    with patch.object(GlmClient, "generate_structured_json", return_value=critic_mock):
        bp = synthesizer.synthesize(
            tree_res=tree_res,
            schema_res=schema_res,
            code_res=code_res,
            use_llm=True,
        )

        assert bp.critic_report is not None
        assert "confirmed_facts" in bp.critic_report
        assert "PLC 急停物理硬接线" in bp.known_unknowns
        assert "机器人底层防碰撞光栅信号" in bp.known_unknowns
