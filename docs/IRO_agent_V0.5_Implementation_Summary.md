# IRO_agent V0.5 落地实施总结 (Implementation Summary)

## 1. 升级概述

IRO_agent V0.5 全面实现了两大核心能力：
1. **True Deep Project Bootstrap (真多轮 GLM 结构化项目自举)**：彻底替换早期伪多轮与纯静态启发式，实现 Stage 0 ~ Stage 9 深度学习流水线，引入针对性模块源码精读与批评审查通道 (Critic Pass)，如实标识未知盲区 (Known Unknowns)。
2. **Investigation Harness (假设驱动排查调查套件)**：构建确定性诊断排查编排层，实行证据分层 (Tier 1A/1B/2/3/4) 与动态优先级算法，建立 2~6 个竞争性假设并由工具评估证据驱动状态演进，设置明确停止条件，在数字证据耗尽时自动升级现场工控硬件物理排查清单 (Checklist)。

---

## 2. 核心架构与模块清单

### Part A: 深度自举流水线 (Deep Bootstrap)
- `iro_agent/knowledge/evidence_bundle.py`: `BootstrapEvidenceBundle` 归集工程树、模块、代码图谱、配置项、数据表及端点等静态证据；
- `iro_agent/knowledge/deep_reader.py`: `TargetedModuleDeepReader` 针对架构提纯确定的重点模块，优先精读 Controller、Service、Mapper、状态机与硬件协议源码；
- `iro_agent/knowledge/synthesizer.py`: 驱动 Stage 1 (架构认知) -> Stage 2 (源码精读) -> Stage 3 (配置系统) -> Stage 4 (DB与状态) -> Stage 5 (业务流) -> Stage 6 (外部系统) -> Stage 7 (Critic Pass) 的真实多轮 GLM 交互；
- `iro_agent/knowledge/bootstrap_report.py`: `BootstrapReportGenerator` 生成标准化 Markdown 报告，汇报模型调用轮次、精读代码量、模块置信度及未知盲区；
- `iro_agent/knowledge/bootstrap.py`: 流水线主控，强制要求有效 API Key（支持 `--static-only` 离线基线模式）。

### Part B: 调查套件 (Investigation Harness)
- `iro_agent/investigation/models.py`: 定义 `EvidenceTier`、`CaseType`、`HypothesisStatus`、`Hypothesis`、`InvestigationStep`、`InvestigationReport`；
- `iro_agent/investigation/classifier.py`: `InvestigationCaseClassifier` 现场异常多标签分类器；
- `iro_agent/investigation/hypotheses.py`: `HypothesisManager` 管理 2~6 个候选假设生命周期 (Confirmed / Strongly Supported / Supported / Ruled Out)；
- `iro_agent/investigation/priorities.py`: `PriorityCalculator` 基于默认层级、故障相关性、预期信息增益与成本计算动态优先级；
- `iro_agent/investigation/evidence_planner.py`: `EvidencePlanner` 规划针对候选假设的工具调用排查步骤；
- `iro_agent/investigation/evaluator.py`: `EvidenceEvaluator` 标准化判定证据为 FACT / SUPPORTING / CONTRADICTING / INCONCLUSIVE / MISSING；
- `iro_agent/investigation/stop_conditions.py`: `StopConditions` 裁决确认结论、强推论收敛、防过度排查与数字证据耗尽；
- `iro_agent/investigation/physical_escalation.py`: `PhysicalEscalation` 数字证据不足时生成针对急停、光电、接线、机械干涉等硬件的排查清单；
- `iro_agent/investigation/harness.py`: `InvestigationHarness` 主控引擎，统领端到端排查循环并输出人类可读诊断答复。

---

## 3. 命令行与使用说明

### 深度项目自举
```bash
# 默认模式：执行真实 GLM 多轮深度认知与源码精读 (必须配置 glm.api_key)
iro-agent init --refresh

# 离线调试：执行纯静态扫描与启发式推断
iro-agent init --refresh --static-only
```

### 运行时故障排查
在控制台交互或 API 网关中，当提问涉及现场故障（如“为什么机器人不走？”、“系统卡在叫料流程”等）时，系统自动路由至 `InvestigationHarness` 执行排查。
