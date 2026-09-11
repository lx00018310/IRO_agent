# IRO_agent Harness Refactor Baseline (2026-09-11)

## 1. 基础环境与代码基线

- **基线日期**: 2026-09-11
- **代码仓库**: `lx00018310/IRO_agent`
- **基线分支**: `main`
- **重构工作分支**: `refactor/harness-engineering-v05`
- **基线 Commit SHA**: `8d1e068820f18df88eddffef747209c9a16771c1`
- **Python 版本**: `Python 3.13.7`
- **平台系统**: Windows (PowerShell)

---

## 2. 单元测试基线

执行命令：
```bash
pytest -q
```

执行结果：
- **测试总数**: 97
- **通过 (Passed)**: 97
- **失败 (Failed)**: 0
- **跳过 (Skipped)**: 0
- **执行总耗时**: 49.67s
- **警告数 (Warnings)**: 10（均为 `lark_oapi` 与 `pkg_resources` / `websockets` 第三方依赖弃用提示）

测试集覆盖清单（共 35 个测试模块）：
1. `tests/test_analyzer_memory.py`
2. `tests/test_bootstrap_business_flows.py`
3. `tests/test_bootstrap_report.py`
4. `tests/test_code_graph.py`
5. `tests/test_config_catalog.py`
6. `tests/test_correction_detection.py`
7. `tests/test_deep_bootstrap.py`
8. `tests/test_deep_bootstrap_critic.py`
9. `tests/test_deep_bootstrap_glm_calls.py`
10. `tests/test_dynamic_priority.py`
11. `tests/test_e2e_scenarios.py`
12. `tests/test_evidence_planner.py`
13. `tests/test_feishu_gateway.py`
14. `tests/test_generic_bootstrap_fixture.py`
15. `tests/test_hypothesis_manager.py`
16. `tests/test_intent_router.py`
17. `tests/test_investigation_harness.py`
18. `tests/test_knowledge_ground_truth.py`
19. `tests/test_knowledge_scanners.py`
20. `tests/test_knowledge_store.py`
21. `tests/test_learning_memory.py`
22. `tests/test_learning_recall.py`
23. `tests/test_log_db_reader.py`
24. `tests/test_physical_escalation.py`
25. `tests/test_readers.py`
26. `tests/test_scanners_java_mybatis_vue.py`
27. `tests/test_security.py`
28. `tests/test_stop_conditions.py`
29. `tests/test_task013_v04_cases.py`
30. `tests/test_v03_graph_accuracy.py`
31. `tests/test_version_provider.py`
32. `tests/test_web_reader.py`
33. `tests/blind_test_task013.py` (注：当前为白盒场景验证，待降级重构)
34. `tests/run_single_blind_test.py`
35. `tests/project_knowledge_ground_truth.json`

---

## 3. 当前配置 Schema (config.example.json)

```json
{
  "project_name": "TASK-013",
  "project_root": "CHANGE_ME_HERE",
  "wrelease_dir": "CHANGE_ME_HERE",
  "log_dirs": [
    "CHANGE_ME_HERE",
    "CHANGE_ME_HERE"
  ],
  "allowed_paths": [],
  "database": {
    "host": "CHANGE_ME_HERE",
    "port": "CHANGE_ME_HERE",
    "user": "CHANGE_ME_HERE",
    "password": "CHANGE_ME_HERE",
    "database": "CHANGE_ME_HERE",
    "connect_timeout": 5
  },
  "glm": {
    "api_key": "YOUR_GLM_API_KEY",
    "api_base": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-5.3-flash",
    "timeout": 60
  },
  "gateway": {
    "type": "feishu",
    "listen_host": "127.0.0.1",
    "listen_port": 8080
  },
  "feishu": {
    "enabled": true,
    "app_id": "YOUR_FEISHU_APP_ID",
    "app_secret": "YOUR_FEISHU_APP_SECRET",
    "bot_name": "IRO_agent",
    "receive_group_at": true,
    "receive_private": true
  },
  "project_mapping": {
    "feishu": {
      "oc_example_chat_id": {
        "project": "TASK-013"
      }
    }
  },
  "storage": {
    "audit_db_path": "iro_agent_audit.db",
    "memory_db_path": "iro_agent_memory.db"
  }
}
```

---

## 4. 当前 CLI 命令定义

入口：`iro_agent/cli.py`
- `iro-agent init`: 初始化或刷新目标工程的业务认知蓝图 (参数: `--project/-p`, `--refresh/-r`, `--static-only`)
- `iro-agent chat`: 启动交互式只读诊断会话 (参数: `--image/-i`)
- `iro-agent config`: 查看当前生效的配置项
- `iro-agent doctor`: 执行工控机与系统环境体检
- `iro-agent gateway`: 网关服务控制 (子命令: `start`, `status`, `doctor`, 参数: `--type`)

---

## 5. 现有核心模块架构

```text
iro_agent/
├── analyzer/
│   └── orchestrator.py
├── gateway/
│   ├── feishu.py
│   └── http_adapter.py
├── investigation/
│   ├── classifier.py
│   ├── evaluator.py
│   ├── evidence_planner.py
│   ├── harness.py
│   ├── hypotheses.py
│   ├── models.py
│   ├── physical_escalation.py
│   ├── priorities.py
│   └── stop_conditions.py
├── knowledge/
│   ├── bootstrap.py
│   ├── bootstrap_report.py
│   ├── business_flows.py
│   ├── code_graph.py
│   ├── config_catalog.py
│   ├── deep_reader.py
│   ├── evidence_bundle.py
│   ├── lookup.py
│   ├── models.py
│   ├── scanners.py
│   ├── store.py
│   └── synthesizer.py
├── llm/
│   └── glm_client.py
├── memory/
│   ├── incident_store.py
│   └── learning_store.py
├── readers/
│   ├── code_reader.py
│   ├── db_reader.py
│   ├── git_reader.py
│   ├── log_reader.py
│   ├── version_provider.py
│   ├── web_reader.py
│   └── wrelease_reader.py
├── router/
│   └── intent_router.py
└── security/
    ├── audit.py
    └── policy.py
```

---

## 6. 基线冻结规范与原则

1. 保持只读安全边界（不得引入写操作）。
2. 不推倒重写已有模块，优先保留向后兼容。
3. 单元测试破坏立即拦截，不得带病进入下一阶段。
