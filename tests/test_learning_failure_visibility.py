import pytest
from unittest.mock import MagicMock
from iro_agent.knowledge.synthesizer import KnowledgeSynthesizer
from iro_agent.knowledge.tree_scanner import TreeScanResult
from iro_agent.knowledge.schema_scanner import SchemaScanResult
from iro_agent.knowledge.code_scanner import CodeScanResult
from iro_agent.knowledge.models import ModuleKnowledge, TableKnowledge, ConfigItem
from iro_agent.memory.incident_store import (
    IncidentStore,
    STATUS_AGENT_DIAGNOSIS,
    STATUS_HUMAN_CONFIRMED,
    VERIFIED_STATUSES,
)
from iro_agent.memory.learning_store import LearningMemoryStore


def test_synthesizer_stage_failure_visibility(tmp_path):
    # Mock TreeScanResult, SchemaScanResult, CodeScanResult
    tree_res = TreeScanResult(
        project_root=str(tmp_path),
        top_level_modules=["backend"],
        primary_language="Java",
        frameworks=["Spring Boot"],
    )

    schema_res = SchemaScanResult(connected=False, tables=[])
    code_res = CodeScanResult()

    synth = KnowledgeSynthesizer()
    
    # 模拟 mock client 在 stage 1 抛出异常
    mock_client = MagicMock()
    mock_client.generate_structured_json.side_effect = RuntimeError("GLM connection timeout")

    # 执行带有异常的 stage_1
    overview, modules, targets = synth._stage_1_architecture_learning(
        tree_res, code_res, mock_client
    )

    # 验证异常未被静默吞掉，而是记录到了 stage_errors
    assert len(synth.stage_errors) == 1
    err = synth.stage_errors[0]
    assert err["stage"] == "stage_1_architecture_learning"
    assert "GLM connection timeout" in err["error"]
    assert err["error_type"] == "RuntimeError"


def test_pure_llm_confidence_downgrade(tmp_path):
    synth = KnowledgeSynthesizer()
    mod = ModuleKnowledge(module_id="m1", name="order_mod", business_role="Old role")
    
    mock_client = MagicMock()
    # 假设 LLM 返回了 CONFIRMED 标签
    mock_client.generate_structured_json.return_value = {
        "business_role": "Dispatches production tasks",
        "confidence": "CONFIRMED",  # 试图宣称已确认
    }

    from iro_agent.knowledge.deep_reader import DeepReadResult, DeepReadFile
    mock_read_res = DeepReadResult(
        files=[DeepReadFile(relative_path="order.py", module="order_mod", category="service", line_count=10, content="code")],
        total_files=1,
        total_lines=10,
    )

    updated_mods = synth._stage_2_module_deep_learning([mod], mock_read_res, mock_client)
    # 按照 Plan 规范，纯 LLM 自动提取最高只能为 STRONGLY_SUPPORTED，必须被自动降级
    assert updated_mods[0].confidence == "STRONGLY_SUPPORTED"


def test_incident_memory_verification_prioritization(tmp_path):
    db_file = tmp_path / "test_memory.db"
    store = IncidentStore(db_path=str(db_file))

    # 写入一个仅有 Agent 自动诊断的未验证记录
    store.record_incident({
        "incident_id": "INC-UNVERIFIED",
        "symptom": "PLC network disconnect",
        "root_cause": "Unchecked agent hypothesis",
        "status": STATUS_AGENT_DIAGNOSIS,
    })

    # 写入一个人工确认过的真实经验记录
    store.record_incident({
        "incident_id": "INC-VERIFIED",
        "symptom": "PLC network disconnect",
        "root_cause": "Optical fiber transceiver power supply failure",
        "status": STATUS_HUMAN_CONFIRMED,
    })

    results = store.find_similar_incidents("PLC network disconnect")
    assert len(results) >= 2

    # 验证 HUMAN_CONFIRMED 案例排在最前，权重最高且 is_verified 为 True
    top = results[0]
    assert top["incident_id"] == "INC-VERIFIED"
    assert top["is_verified"] is True
    assert top["evidence_weight"] == 1.0

    second = results[1]
    assert second["incident_id"] == "INC-UNVERIFIED"
    assert second["is_verified"] is False
    assert second["evidence_weight"] < 0.5


def test_learning_memory_anti_pollution(tmp_path):
    db_file = tmp_path / "test_learning.db"
    store = LearningMemoryStore(db_path=str(db_file))

    store.save_rule({
        "rule_id": "RULE-TEST-01",
        "rule_text": "遇到 408 必须优先检查机器人回调心跳",
        "topic": "robot",
        "source_type": "user_correction",
        "confidence": "confirmed",
    })

    recalled = store.recall_rules("408 机器人故障")
    assert len(recalled) == 1
    rule = recalled[0]

    # 验证防污染元数据完整
    assert rule["is_current_fact"] is False
    assert rule["guidance_role"] == "prior_bias_only"
    assert rule["verification_type"] == "user_correction"
    assert "verified_at" in rule
