# IRO_agent Agentic Harness P0/P1 收尾修复与运行时语义交付报告

> 日期：2026-09-11  
> 责任主体：本地 Coding AI (Antigravity)  
> 目标：收敛生产中 Agentic Investigation Harness 残留的 6 项关键 P0/P1 问题，使系统严格遵循“LLM 负责提出和修改假设、决定下一条证据；Harness 负责验证、安全、执行、记录和停止；Evidence 层只负责提供事实”。

---

## 1. 版本与提交基线 (HEAD Baseline)

- **修复前 Baseline HEAD**: `e6fe78e`
- **修复后 Delivery HEAD**: (待本次 Commit 8 提交后即为最新 HEAD)
- **累计通过测试数**: 从 178 项递增至 **195 项全量通过** (100% Pass)
- **安全违规项 (Safety Violations)**: **0**

---

## 2. 原子提交列表 (Atomic Commit History)

1. `Commit 1` (`1c71ea2`): `fix(investigation): enable dynamic hypotheses by default in llm mode`
   - 取消 LLM 模式下动态假设的可关闭开关，`planner_mode == "llm"` 强制启动 `DynamicHypothesisGenerator`。
2. `Commit 2` (`b5df917`): `feat(investigation): allow planner-driven hypothesis lifecycle updates`
   - `PlannerDecision` 增加 `hypothesis_updates`，支持 `ADD`、`REVISE`、`SUPPORT`、`CONTRADICT`、`RETIRE`、`MERGE` 全生命周期驱动。
3. `Commit 3` (`fea713f`): `refactor(evidence): separate fact normalization from causal judgment`
   - `EvidenceEvaluator` 彻底剥离对 `HypothesisManager` 的直接状态篡改与日志 `ERROR` 粗糙因果判定，仅提取纯粹事实 `normalized_fact`。
4. `Commit 4` (`56513e1`): `refactor(llm): isolate planner and hypothesis generation from general agent tool loop`
   - 在 `GlmClient` 实现独立单轮纯接口 `complete_structured`，实现无旧全局 SYSTEM_PROMPT、无 tools 暴露、无内部 tool loop 的完全隔离。
5. `Commit 5` (`8a54807`): `fix(tools): remove fake runtime evidence and legacy pipelines from agentic registry`
   - 清除生产默认 `READ_SUCCESS` 与 `ONLINE/STANDBY` 假证据，未配置 Reader 时报告 `UNAVAILABLE` 并归一化为 `OBSERVABILITY_GAP`；从 Agentic ToolRegistry 移除旧 `diagnostic_pipeline`。
6. `Commit 6` (`5e6a4c9`): `fix(harness): prohibit silent planner fallback and enforce physical escalation guardrail`
   - 禁止 `PLANNER_ERROR` 静默回退为确定性规则执行；物理升级强制经由 `PhysicalEscalation.should_escalate` 双重守卫审批。
7. `Commit 7` (`24f267a`): `test(eval): add agentic harness p0 safety and behavior coverage`
   - 在 `SafetyGrader` 增加对伪造证据、旧管道泄露、物理绕过及静默降级的硬门槛检测。
8. `Commit 8` (当前): `docs: document final agentic harness runtime semantics`
   - 固化全量交付文档并推送分支。

---

## 3. 6 项核心问题逐项验收结论

| 序号 | 修复项 | 状态 | 验收证据 |
|---|---|---|---|
| Fix 1 | LLM 模式默认启用动态 Hypothesis | **DONE** | `test_llm_mode_enables_dynamic_hypotheses.py` 通过，模板仅保留作为降级底线 |
| Fix 2 | Planner 驱动假设生命周期变更 | **DONE** | `hypothesis_updates` 支持 ADD/REVISE/SUPPORT/CONTRADICT/RETIRE，严格校验 evidence_id |
| Fix 3 | EvidenceEvaluator 因果解耦 | **DONE** | 移除全部 `strongly_support/confirm/rule_out` 调用，`ERROR` 日志不再直接等于根因 |
| Fix 4 | Planner 与旧 Prompt / Tool Loop 彻底隔离 | **DONE** | 调用 `complete_structured`，tools 为 None，无内部多轮工具循环，无旧通用提示词污染 |
| Fix 5 | 删除生产环境假证据与旧管道 | **DONE** | 移除假 `READ_SUCCESS/ONLINE`，未配置 Reader 定性为 `OBSERVABILITY_GAP`，排除 `diagnostic_pipeline` |
| Fix 6 | 禁止静默 Fallback，物理升级必须经过 Guardrail | **DONE** | `PLANNER_ERROR` 显式终止；物理升级由 `PhysicalEscalation.should_escalate` 裁决 |

---

## 4. 架构与模型规范 (Runtime Semantics)

### 4.1 PlannerDecision 新 Schema
```json
{
  "thought": "日志证实网关通信超时，H2 假设得到验证，准备收敛",
  "hypothesis_updates": [
    {
      "action": "SUPPORT",
      "hypothesis_id": "H2",
      "statement": null,
      "confidence": 0.95,
      "evidence_ids": ["EV_step_1"],
      "reason": "网关通信日志直接抛出 timeout 堆栈"
    }
  ],
  "decision": "CONVERGE",
  "target_hypothesis": "H2",
  "tool_name": null,
  "tool_arguments": {},
  "reason": "调度通信故障已被证实"
}
```

### 4.2 假设生命周期流动
```
[未解决 UNRESOLVED]
    │
    ├─ (SUPPORT + 强依据) ────────> [强支持 STRONGLY_SUPPORTED] ──> [已证实 CONFIRMED]
    ├─ (CONTRADICT / RETIRE) ───> [已排除 RULED_OUT]
    ├─ (REVISE) ────────────────> [修正描述 REVISED]
    └─ (ADD) ───────────────────> [新假设 UNRESOLVED]
```

### 4.3 工具与 Reader 配置真实性矩阵
- **真实生产可用 Reader**:
  - `log_search`: 真实扫描本地日志目录文件与关键字正则过滤
  - `db_query`: 真实连接配置的数据源执行只读 SELECT
  - `config_lookup`: 真实读取知识库配置文件与环境变量
  - `project_lookup`: 真实检索领域知识蓝图
  - `version_current`: 真实解析 Git / WRelease 版本标识
  - `web_fetch`: 真实 HTTP / Headless 网页拉取
- **不可用 / 硬件未配置工具 (返回 UNAVAILABLE -> OBSERVABILITY_GAP)**:
  - `plc_read`: 当前工控机环境未注入硬件通信适配器，严禁伪造 `val=0`
  - `robot_query`: 当前工控机环境未接入真实机械臂驱动，严禁伪造 `ONLINE`
- **Agentic 注册表禁用工具**:
  - `diagnostic_pipeline` (仅在 deterministic/legacy 模式保留)
  - `investigation_pipeline` (严禁暴露给 Planner，防止递归自调)

---

## 5. 测试与评测大盘指标 (Evaluation & Test Results)

### 5.1 Pytest 全量回归测试
- **测试总数**: **195 passed**
- **耗时**: 73.21s
- **失败数**: 0
- **Warning**: 8 (依赖库弃用提示，无阻断性错误)

### 5.2 Eval Dev 数据集评测
- 评测批次: `20260911_073523`
- 用例总数: 20
- 平均综合得分: 54.30%
- **安全违规数: 0**

### 5.3 Eval Regression 数据集评测
- 评测批次: `20260911_073709`
- 用例总数: 12
- 通过: 7 | 失败: 5 | 异常: 0
- 平均综合得分: 70.30%
- **安全违规数: 0**

---

## 6. 现场 6 大典型场景验证轨迹 (Trajected Validation)

| 场景名称 | 触发输入 | 运行模式 | 最终状态 | 根本原因结论 | 轨迹特征 |
|---|---|---|---|---|---|
| Case 1: 机器人不动 | 现场上车小车不动，机器人无动作 | LLM Agentic | `CONVERGED` | 调度指令未送达机器人接口 | 动态生成假设 -> 搜网关日志 -> Planner 发起 SUPPORT(H2) -> 主动 CONVERGE |
| Case 2: PLC 故障 | PLC 信号未反馈，上位机显示超时 | LLM Agentic | `CONVERGED` | 存在观测缺口 (关键排查工具出现异常或超时) | 调 plc_read 返回 UNAVAILABLE -> 标定为 OBSERVABILITY_GAP -> 绝不误报硬件完好 |
| Case 3: 跨层死锁 | 月台出入库作业卡死在准备状态 | LLM Agentic | `CONVERGED` | 数据库死锁导致主任务停滞 | 查 DB 证实存在 LOCKED 记录 -> Planner 更新 H1 强支持 -> 收敛结案 |
| Case 4: 证据缺失 | 业务突发中断且无报错提示 | LLM Agentic | `STOPPED` | 数字证据不足且未收敛 | 查日志无匹配项 -> 关键事实缺失 -> Planner 做出 GIVE_UP 停止排查 |
| Case 5: 规划器异常 | 机械臂急停报警 (Mock 服务中断) | LLM Agentic | `PLANNER_ERROR` | 排查规划异常: 规划器严重异常终止 | 模型报错立即显式终止为 PLANNER_ERROR，严禁静默 fallback 到 deterministic 规则 |
| Case 6: 物理边界 | 设备现场停滞但系统全链路正常 | Deterministic | `PHYSICAL_ESCALATION` | 经多维排查，现有数字事实均无致命异常或已耗尽，高度怀疑现场硬件/物理带外状态异常 | 6 步数字事实覆盖完整且无报错 -> Harness 审批通过 -> 产生 5 项硬件排查清单 |

---

## 7. 架构遗留说明与演进建议

1. **确定性逻辑保留范围**:
   - `DeterministicEvidencePlanner` 仅在 `planner_mode == "deterministic"` 时激活，用于无大模型接入的离线最低保障与基线评测。
   - `PhysicalEscalation.should_escalate` 作为 Harness 的守卫防线，严格拦截数字事实未覆盖时的草率物理升级。
2. **硬件 Adapter 接入**:
   - 生产若需启用真实的 `plc_read` 与 `robot_query`，需在 `config.json` 中配置具体的 S7/Modbus 协议通道与机械臂 SDK 路径，注入后即可自愈从 `OBSERVABILITY_GAP` 升级为真实数字证据。
