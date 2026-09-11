# IRO_agent Agentic Harness P0/P1 修复前运行基线 (2026-09-11)

---

## 1. 版本与测试基线

- **Git HEAD SHA**: `e6fe78ed24ea40a00251bf4173f7e13d95c4bb32`
- **全量自动化测试基线**: `167 passed, 8 warnings in 77.48s`
- **安全违规基线**: `0`

---

## 2. 核心参数与行为现状核查

| 检查项 | 当前代码状态 | 文件与行号 | 存在问题 |
| :--- | :--- | :--- | :--- |
| **`dynamic_hypotheses` 默认值** | `False` | [`harness.py:55`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/harness.py#L55) | LLM 模式下若未显式传参 `dynamic_hypotheses=True`，仍会降级至固定模板 |
| **Planner 调用的 GLM API** | `glm_client.chat_completion(...)` | [`llm_planner.py:100`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/llm_planner.py#L100) | 注入全局旧版 `SYSTEM_PROMPT` 并开启内部工具调用循环，造成双重 Agent 循环 |
| **Hypothesis 生成调用的 GLM API** | `glm_client.chat_completion(...)` | [`hypotheses.py:65`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/hypotheses.py#L65) | 同样受旧全局 `SYSTEM_PROMPT` 与全局工具 schema 污染 |
| **生产默认 Tool Handlers** | 内置虚假硬件 stub | [`harness.py:107-108`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/harness.py#L107-L108) | `plc_read: {"status": "READ_SUCCESS", "val": 0}`, `robot_query: {"status": "ONLINE"}` 伪造数据 |
| **`diagnostic_pipeline` 暴露状态** | 默认注册并暴露 | [`tool_registry.py:158`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/tool_registry.py#L158), [`harness.py:105`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/harness.py#L105) | LLM Planner 可重新钻回旧版单向固定流水线 |
| **Planner Error 处理逻辑** | 静默 fallback | [`harness.py:183-190`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/harness.py#L183-L190) | 遇大模型异常或格式错误自动重设 `self.planner_mode = "deterministic"` |
| **Physical Escalation 审批权** | LLM 自行决定 | [`harness.py:199-206`](file:///D:/00_personalwork/IRO_agent/iro_agent/investigation/harness.py#L199-L206) | LLM 规划器返回 `ESCALATE_PHYSICAL` 直接采纳，未调用 `PhysicalEscalation.should_escalate` |

---

## 3. 评测集基线 (Evaluation Baseline)

- **DEV Dataset (20 Cases)**: 5 passed / 15 failed / 0 infra_error, 平均分 75.50%
- **REGRESSION Dataset (12 Cases)**: 4 passed / 8 failed / 0 infra_error, 平均分 78.10%
