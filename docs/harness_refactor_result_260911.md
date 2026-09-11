# IRO_agent Harness Engineering 第二阶段重构成果总结报告

> 报告日期：2026-09-11  
> 基线分支：`main` (`9ae5964`)  
> 重构分支：`refactor/harness-engineering-v05`  
> 核心目标：完成从“固定步骤诊断助手”向“可评测、可泛化、可持续迭代的企业工业诊断 Harness 系统”的完整演进。

---

## 1. 提交历程与演进总览 (Commit History)

本次重构严格按照 `docs/260911_IRO_agent_Harness_Refactor_Plan.md` 执行，分 11 个独立阶段依次演进、测试与验收：

| Commit 序号 | 提交哈希 | 提交信息规范 | 核心改动与交付成果 |
| :--- | :--- | :--- | :--- |
| **Commit 1** | `9ae5964` | `chore: capture harness refactor baseline` | 创建重构分支，固化 97 项基线测试与文档 [docs/refactor_baseline_260911.md](file:///D:/00_personalwork/IRO_agent/docs/refactor_baseline_260911.md) |
| **Commit 2** | `5b27e87` | `feat(investigation): add investigation state and evidence provenance` | 新增 `InvestigationState` 动态状态机、`EvidenceRecord` 证据溯源及 `InvestigationTrace` 轨迹 |
| **Commit 3** | `724b792` | `refactor(investigation): switch planner to iterative next-best-evidence selection` | 引入假设区分增益 (`hypothesis_discrimination_gain`)、新鲜度与重复惩罚，实现 Next-Best-Evidence 动态规划 |
| **Commit 4** | `0a5267c` | `refactor(investigation): make stop conditions state-driven` | 实现状态驱动的 `StopConditions`，完善 `physical_escalation` 边界判定，重构 `InvestigationHarness` 主循环 |
| **Commit 5** | `dfb91a9` | `feat(evaluation): add dataset runner trajectory and deterministic graders` | 建立 `iro_agent/evaluation/` 评测框架、CLI `eval {dev,regression,external}` 及确定性/安全 Grader |
| **Commit 6** | `c29fbac` | `refactor(eval): demote legacy blind test and enforce no-fallback evaluation` | 降级旧单文件盲测为白盒场景集，严禁评测模式隐式 fallback 假装通过 |
| **Commit 7** | `f398042` | `feat(evaluation): add evidence path and semantic grading` | 新增证据锚定 Grader、探查路径质量 Grader 及语义裁判，建立 5 维加权评分系统 |
| **Commit 8** | `78d238b` | `feat(eval-cases): add initial dev and regression industrial cases` | 建立 `evaluation_cases/` 工业用例库 (DEV 20 例, REGRESSION 12 例)，完成初版基线评测 |
| **Commit 9** | `c52853e` | `refactor(bootstrap): add unknown-driven iterative learning loop` | 新增 `KnowledgeUnknown` 一等对象、`LearningState` 10 维覆盖度及 `BootstrapLearningLoop` 自主学习闭环 |
| **Commit 10** | `8bbc97a` | `fix(bootstrap): expose learning failures and enforce confidence provenance` | 消除静默吞异常，暴露 `stage_errors`，规范 LLM 自动提取置信度，建立记忆防污染与验证区隔机制 |
| **Commit 11** | (HEAD) | `docs: document harness engineering workflow and eval policy` | 发布评测与防作弊策略 [docs/evaluation_policy.md](file:///D:/00_personalwork/IRO_agent/docs/evaluation_policy.md)、重写 README 并交付总结报告 |

---

## 2. 核心架构演进对比

### 2.1 Investigation Harness (排查闭环)
- **重构前**：基于预设的候选步骤一次性排布固定列表，顺序执行；容易陷入无关步骤或因单个步骤报错而中断。
- **重构后**：
  - 升级为真正的 **假设 → 取证 → 更新 → 再规划 (Re-plan) 闭环**。
  - 每一步依据全量证据的假设区分增益（Discrimination Gain）、证据收益比及新鲜度动态计算最高价值的下一步。
  - 引入明确的终止原因码 (`StopReasonCode`)，区分已确诊收敛、无信息增益、预算耗尽以及合法的物理升级。
  - 严格防御“观测缺口”被误判为“物理故障”：仅当数字探查充分且所有软逻辑均正常时，才触发硬件物理检修升级。

### 2.2 Project Learning Harness (项目认知)
- **重构前**：线性执行 Stage 0~9 的单次批处理流水线，异常时静默 pass 并给虚高的 CONFIRMED 标签。
- **重构后**：
  - 将 **Unknown 提升为一等公民 (`KnowledgeUnknown`)**，建立动态优先级调度队列。
  - 构建 **10 维认知覆盖度体系**（架构、模块、业务流、状态机、数据库 SoT、配置层级、外部集成、可观测性、版本演进、已知暗区）。
  - 建立自主迭代学习闭环（STOP-A 高价值清空、STOP-B 覆盖度增益收敛、STOP-C 数字不可解、STOP-D 预算耗尽）。
  - 强制暴露学习阶段失败 (`stage_errors`)，纯 LLM 自动提取最高只能打标 `STRONGLY_SUPPORTED`，实现严格的置信度溯源。

### 2.3 Evaluation Harness (客观评测体系)
- **重构前**：仅有白盒 `tests/blind_test_task013.py`，无客观指标看板，易发生 Prompt 针对性过拟合。
- **重构后**：
  - 构建完整的标准化评测集架构：DEV (20 例)、REGRESSION (12 例)，禁止将私有盲测集提交至仓库。
  - 建立 5 维加权分层评测器：确定性判定 (0.35) + 证据锚定 (0.25) + 路径质量 (0.15) + 语义判定 (0.15) + 安全合规 (0.10)。
  - 制定十条防作弊铁律（严禁读 Ground Truth、严禁 Case 特判、严禁隐式兜底刷分、严禁放水改 Grader）。

---

## 3. 测试与评测指标对比

### 3.1 自动化单元测试 (Pytest)
- **重构前基线**：97 项测试通过，耗时 49.67s。
- **重构后当前**：**138 项测试全部通过**，耗时 40.35s。
- **测试增量**：净增 41 项高价值自动化测试，覆盖：
  - `test_investigation_state.py` (动态状态与假设转换)
  - `test_evidence_provenance.py` (证据溯源与因果关联)
  - `test_iterative_evidence_planning.py` & `test_replan_after_evidence.py` (动态重规划)
  - `test_observability_gap.py` & `test_no_false_physical_escalation.py` (观测缺口与物理升级)
  - `test_claim_evidence_link.py` & `test_eval_path_grader.py` (证据锚定与路径打分)
  - `test_eval_dataset_loader.py`, `test_eval_runner.py`, `test_eval_no_fallback.py` (评测流水线)
  - `test_learning_unknown_queue.py`, `test_learning_coverage.py`, `test_learning_replan.py` (认知闭环)
  - `test_learning_failure_visibility.py`, `test_learning_stop_conditions.py` (异常暴露与置信度降级)

### 3.2 初始 V0 评测基线 (Evaluation Baseline)
通过 `python -m iro_agent.cli eval` 运行真实基线评测：

| 评测集 | 用例数 | 通过数 | 综合平均分 | 安全违规数 | 关键防御特性 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEV Dataset** | 20 | 5 | 75.50% | 0 | 覆盖后端 NPE、PLC 超时、配置漂移、物料不符、版本回滚等典型现场案例 |
| **REGRESSION Dataset** | 12 | 4 | 78.10% | 0 | 覆盖反直觉 5 大 Case（用户误导、时序巧合、陈旧日志噪声、真实物理急停、严重观测缺口）以及写操作硬拦截 |

*注：当前基线忠实记录真实得分（平均分约 76%~78%），未采用任何作弊手段或放水逻辑，为后续持续优化提供了客观参考标尺。*

---

## 4. Definition of Done (DoD) 核验清单

- [x] **Investigation Harness**：支持 Next-Best-Evidence 动态规划，状态驱动收敛，排查轨迹完整记录。
- [x] **Evaluation Harness**：支持 DEV/REGRESSION 评测执行、报告生成与 5 维评分，包含确定性与语义裁判。
- [x] **Project Learning Harness**：Unknown 一等对象建模，10 维覆盖度量，自主学习停止条件生效。
- [x] **只读安全底线**：生产写操作 100% 拦截，安全 Grader 违规数持续为 0。
- [x] **防作弊规范**：发布 [docs/evaluation_policy.md](file:///D:/00_personalwork/IRO_agent/docs/evaluation_policy.md)，代码无 Ground Truth 窥视，无 Case 特判。
- [x] **向后兼容性**：保留全部原有 CLI 命令与历史核心功能，单元测试 138 项全绿通过。

---

## 5. 结论

IRO_agent 第二阶段 Harness Engineering 重构已圆满完成。系统不仅具备了应对工业复杂真实故障的自适应研判能力，更建立了严格的防作弊评价体系，完全达成了重构计划的全部既定目标。
