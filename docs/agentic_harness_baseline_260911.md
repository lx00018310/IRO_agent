# IRO_agent Agentic Investigation Harness 改造前基线报告

> 记录日期：2026-09-11  
> 基线 HEAD SHA：`5616256d537b5ba6043f8a50af5d90dbd8eee987`  
> 单元测试状态：138 passed, 8 warnings (38.25s)  
> 评测基线：DEV (20例, 均分 75.50%), REGRESSION (12例, 均分 78.10%), 安全违规 0

---

## 1. 现状三条执行链分析

### 1.1 Feishu 生产执行链
- **源码位置**：`iro_agent/gateway/feishu.py` (`_process_message_async`)
- **当前路径**：
  ```text
  飞书事件接收 (im.message.receive_v1)
    │
    ▼
  文本与图片提取 (清洗 @_user_xxx)
    │
    ▼
  学习规则记忆库召回 (learning_store.recall_rules)
    │
    ▼
  拼接 Prompt 到会话历史 (session_history)
    │
    ▼
  调用 glm_client.chat_completion(history, ...)  <-- 缺陷：直接调用通用 LLM
    │
    ▼
  脱敏并回送飞书群聊
  ```
- **核心问题**：完全没有调用 `IntentRouter` 或 `InvestigationHarness`，生产环境完全脱离 Harness 控制。

### 1.2 CLI 对话执行链
- **源码位置**：`iro_agent/cli.py` (`run_chat`)
- **当前路径**：
  ```text
  CLI 输入
    │
    ▼
  IntentRouter.route(clean_prompt)  <-- 仅打印 "[意图路由] 判定为: runtime_fault"
    │
    ▼
  学习规则召回并拼接
    │
    ▼
  调用 engine.chat_completion(history, ...)  <-- 缺陷：依然走普通 Chat
    │
    ▼
  控制台打印回复
  ```
- **核心问题**：即使意图识别为 `RUNTIME_FAULT`，仍走通用单体 Chat，没有转入 `InvestigationHarness`。

### 1.3 Eval 评测执行链
- **源码位置**：`iro_agent/evaluation/runner.py` (`run_case`)
- **当前路径**：
  ```text
  EvalCase (输入 symptom, mock_readers)
    │
    ▼
  构造 InvestigationHarness(tool_handlers=mock_tools)
    │
    ▼
  调用 harness.investigate(symptom)
    │
    ▼
  输出 InvestigationReport 并进入 Graders 打分
  ```
- **核心问题**：Eval 绕过了生产的 Router/Dispatcher 链路，形成“评测测 Harness，生产走 Chat”的严重割裂。

---

## 2. 现有排查与规划逻辑缺陷

1. **HypothesisManager 依然与 CaseType 强耦合**：
   - 依赖 `InvestigationCaseClassifier.classify(symptom)` 给出 `CaseType`；
   - 依赖预设的 `PLC_SIGNAL_ERROR`、`ROBOT_EXECUTION_ERROR` 等固定模板初始化假设；遇到新型未预设故障时无法自适应生成假设。
2. **EvidencePlanner 仍由确定性启发式驱动**：
   - 依靠 Python 预置权重计算 `score_candidate_step`；未接入大模型每一轮基于证据状态的结构化决策。
3. **缺乏严格的 Planner 决策结构与安全校验**：
   - 没有 `PlannerDecision` 结构体，没有对 LLM 输出的工具名称、参数、只读权限和剩余预算做统一硬门槛拦截。

---

## 3. 本次 Agentic 重构目标矩阵

- [ ] 新建 `RuntimeDispatcher`，统一 Feishu / CLI / Eval 的故障分发入口。
- [ ] 故障输入强制进入 `InvestigationHarness`。
- [ ] 引入 `LLMInvestigationPlanner`，输出严格 JSON `PlannerDecision`。
- [ ] 引入 `PlannerValidator`，严格只读白名单、参数校验与 1 次自动修复重试。
- [ ] `HypothesisManager` 转变为纯状态机，支持首轮动态生成与后续动态修订。
- [ ] 逐轮依据新 Evidence 重新规划，消除固定执行链。
- [ ] 保持安全违规 = 0，单元测试 100% 通过。
