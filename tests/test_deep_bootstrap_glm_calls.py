import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from iro_agent.config import IROConfig, GlmConfig
from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.llm.glm_client import GlmClient


def test_bootstrap_fails_without_api_key(tmp_path):
    """验证未配置 API Key 且未传入 static_only 时，自举必须显式报错，绝不伪装静默成功"""
    cfg = IROConfig()
    cfg.project_root = str(tmp_path)
    cfg.project_name = "TEST-PROJECT"
    cfg.glm = GlmConfig(api_key="YOUR_GLM_API_KEY")

    bootstrapper = ProjectKnowledgeBootstrapper(cfg)
    with pytest.raises(ValueError, match="未配置有效的 GLM API Key"):
        bootstrapper.run_bootstrap(refresh=True, use_llm=True, static_only=False)


def test_bootstrap_static_only_bypasses_glm(tmp_path):
    """验证指定 static_only 时，可以离线无缝运行，不发起 GLM 调用"""
    cfg = IROConfig()
    cfg.project_root = str(tmp_path)
    cfg.project_name = "TEST-PROJECT"
    cfg.glm = GlmConfig(api_key="YOUR_GLM_API_KEY")

    # 创建一个简单源码文件
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "TaskController.java").write_text("public class TaskController {}", encoding="utf-8")

    bootstrapper = ProjectKnowledgeBootstrapper(cfg)
    bp = bootstrapper.run_bootstrap(refresh=True, static_only=True)
    assert bp is not None
    assert bp.bootstrap_stats["glm_calls"] == 0


def test_deep_bootstrap_invokes_real_glm(tmp_path):
    """验证深度自举真实调用了 GLM 模型进行结构化抽取 (Stage 1 ~ 7)"""
    cfg = IROConfig()
    cfg.project_root = str(tmp_path)
    cfg.project_name = "TASK-013"
    cfg.glm = GlmConfig(api_key="fake-real-key-for-test", model="glm-5.3-flash")

    src_dir = tmp_path / "backend"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "DockTaskController.java").write_text(
        "public class DockTaskController { public void callMaterial() {} }",
        encoding="utf-8",
    )

    bootstrapper = ProjectKnowledgeBootstrapper(cfg)

    # 模拟 GlmClient.generate_structured_json
    mock_responses = [
        # Stage 1: Architecture
        {
            "project_purpose": "自动上车现场控制系统",
            "major_runtime_components": ["BackendService", "RobotBridge"],
            "module_responsibilities": {"backend": "后端调度与工控交互"},
            "deep_read_targets": ["backend"],
            "known_unknowns": ["PLC报文协议未完全明确"],
        },
        # Stage 2: Module Deep Reading
        {
            "business_role": "后端核心业务调度",
            "entry_points": ["/api/dock/task"],
            "important_classes": ["DockTaskController"],
            "important_services": ["DockService"],
            "important_tables": ["dock_task"],
            "important_configs": ["timeout_ms"],
            "state_transitions": ["PENDING -> RUNNING"],
            "external_dependencies": ["PLC", "Robot"],
            "known_unknowns": [],
            "confidence": "CONFIRMED",
        },
        # Stage 3: Config Learning
        {
            "refined_configs": [
                {"key": "app.port", "business_meaning": "服务端口", "unit": "port", "runtime_scope": "app", "priority": 50}
            ]
        },
        # Stage 4: DB & State
        {
            "tables": [
                {
                    "table_name": "dock_task",
                    "table_type": "current_state",
                    "business_role": "月台任务实时状态表",
                    "not_for": ["历史报文对账"],
                    "confidence": "CONFIRMED",
                }
            ]
        },
        # Stage 5: Business Flow
        {
            "business_flows": [
                {
                    "flow_id": "material_call",
                    "name": "自动叫料流程",
                    "aliases": ["叫料", "出库"],
                    "steps": ["接收请求", "下发PLC指令"],
                    "controller": "DockTaskController",
                    "services": ["DockService"],
                    "tables": ["dock_task"],
                    "states": ["PENDING", "COMPLETED"],
                    "external_systems": ["PLC"],
                    "source_of_truth": "dock_task.current_status",
                    "unknown_steps": [],
                    "confidence": "CONFIRMED",
                }
            ]
        },
        # Stage 6: External System
        {
            "external_systems": [
                {
                    "system_name": "PLC控制单元",
                    "connection_type": "Modbus TCP",
                    "used_by_module": "backend",
                    "config_source": "plc.cfg",
                    "related_logs": ["plc.log"],
                    "confidence": "CONFIRMED",
                }
            ]
        },
        # Stage 7: Critic Pass
        {
            "confirmed_facts": ["月台任务实时状态为主源"],
            "strongly_inferred_facts": ["PLC通信采用Modbus协议"],
            "weak_inferences": [],
            "unknown_areas": ["PLC硬件急停信号寄存器"],
            "contradictions": [],
        },
    ]

    responses_map = {
        "架构认知": mock_responses[0],
        "深读分析": mock_responses[1],
        "配置系统": mock_responses[2],
        "数据库表": mock_responses[3],
        "业务流": mock_responses[4],
        "外部接口": mock_responses[5],
        "Critic": mock_responses[6],
    }

    def fake_structured_json(*args, **kwargs):
        prompt_text = kwargs.get("prompt", "") or (args[0] if args else "")
        for k, v in responses_map.items():
            if k in prompt_text:
                return v
        return {"status": "ok"}

    with patch.object(GlmClient, "generate_structured_json", side_effect=fake_structured_json) as mock_method:
        bp = bootstrapper.run_bootstrap(refresh=True, use_llm=True)
        assert mock_method.called
        assert mock_method.call_count >= 5, f"GLM 必须在各阶段被真实调用，当前调用次数: {mock_method.call_count}"
        assert bp.bootstrap_stats["glm_calls"] >= 5
        assert len(bp.business_flows) > 0
        assert bp.critic_report is not None
        assert "PLC硬件急停信号寄存器" in bp.known_unknowns
