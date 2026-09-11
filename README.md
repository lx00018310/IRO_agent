# IRO_agent (Industrial Read-Only Agent)

> **IRO_agent is an evidence-driven industrial diagnosis harness.**  
> It learns a project's operational model, investigates incidents through iterative evidence gathering, and evaluates its own diagnosis quality through reproducible datasets.

[![Tests](https://img.shields.io/badge/tests-138%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()
[![Security](https://img.shields.io/badge/boundary-Strict%20Read--Only-red.svg)]()

---

## 核心设计理念

工业现场诊断与常规对话 Agent 有根本不同：工业排查面临高并发日志噪声、用户主观误导、时序巧合与物理断电断网等反直觉场景。IRO_agent 放弃了传统的“一次性固定步骤排查”，演进为三大工业级 Harness 闭环系统：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        IRO_agent 三大核心 Harness                       │
├────────────────────────┬───────────────────────┬───────────────────────┤
│ Project Learning       │ Investigation         │ Evaluation            │
│ Harness                │ Harness               │ Harness               │
├────────────────────────┼───────────────────────┼───────────────────────┤
│ • Unknown 一等对象     │ • Next-Best-Evidence  │ • 确定性 Grader       │
│ • 10 维知识覆盖度跟踪  │ • 动态再规划 (Re-plan)│ • 证据锚定度评分      │
│ • 多轮迭代代码精读     │ • 物理故障升级与收敛  │ • 路径质量与安全审计  │
│ • 置信度校准与防污染   │ • 内部状态轨迹溯源    │ • DEV / REGRESSION 库 │
└────────────────────────┴───────────────────────┴───────────────────────┘
```

1. **绝对只读安全硬防御 (Strict Read-Only)**：无写文件、无执行 Shell、无提交 Git、无写 DB 权限。双层只读拦截与脱敏审计，严守生产安全底线。
2. **严禁无据断言 (Evidence Provenance)**：所有推断均需绑定具体的日志行、配置键或数据库记录，禁止凭空猜测。
3. **真实物理与数字边界划分**：数字观测充分无异常时，支持合法的现场物理排查升级，避免将观测缺口盲目定性为硬件故障。

---

## 核心子系统架构

### 1. Investigation Harness (迭代式排查系统)
- **动态状态机 (`InvestigationState`)**：跟踪假设空间、证据链条、工具调用开销与排查轨迹。
- **Next-Best-Evidence 规划器**：依据假设区分增益（Discrimination Gain）、证据新鲜度与重复调用惩罚，自适应决定下一有效探查动作。
- **状态驱动停止条件 (`StopConditions`)**：收敛判定、最大步数限制与预算保护，告别硬编码固定顺序。

### 2. Project Learning Harness (项目认知学习系统)
- **Unknown 一等对象 (`KnowledgeUnknown`)**：显式建模业务流盲区、硬件交互不确定性及配置差异。
- **多维覆盖度量 (`LearningState`)**：涵盖架构、模块、业务流、状态机、数据库黄金源等 10 个维度，依据覆盖度收益与优先级自主推进。
- **防污染记忆机制**：历史经验严格作为先验参考 (`prior_bias_only`)，严禁直接作为当前根因凭证。

### 3. Evaluation Harness (客观评测体系)
- **多维评测指标**：涵盖 Case 通过率、根因准确率、证据锚定得分、路径质量与安全违规监控。
- **分层 Grader 体系**：
  - `DeterministicGrader`：严格校验根因分类、责任边界与关键关键词。
  - `EvidenceGroundingGrader`：核验所有结论主张与真实工具观测记录的溯源关系。
  - `SafetyGrader`：检测任何写操作企图、破坏性指令与敏感数据泄露。
  - `PathQualityGrader`：评估探索效率，检测死循环与无效试探。
- **严格防作弊规范**：详见 [docs/evaluation_policy.md](docs/evaluation_policy.md)。严禁读取 ground truth、严禁 Prompt 特判、严禁评测模式隐式兜底刷分。

---

## 数据集分层规范

| 数据集 | 目录 | 用途与说明 |
| :--- | :--- | :--- |
| **DEV Dataset** | `evaluation_cases/dev/` | 面向算法开发和 AI 提示工程迭代，包含 20+ 工业真实场景与边界案例。 |
| **REGRESSION Dataset** | `evaluation_cases/regression/` | 质量守门集，包含反直觉 5 大 Case、安全防御以及历史缺陷案例。 |
| **BLIND Dataset** | 外部私有目录（严禁入库） | 生产级盲测集，开发阶段完全不可见，用于最终准入准出验证。 |

---

## 快速上手与部署指引

### 1. 安装与依赖

根据现场工控机环境选择以下方式之一：

#### 方式 A：原生 Python（适用于已安装标准 Python 的环境）

```bash
# 1. 创建虚拟环境 (推荐 Python 3.10+)
python -m venv .venv

# 2. 激活虚拟环境
# Git Bash:
source .venv/Scripts/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

# 3. 安装项目依赖
pip install -e .
```

#### 方式 B：单文件 `uv.exe`（推荐现场嵌入式精简 Python / 离线环境）

> 工业现场若使用 `embed-amd64` 精简版 Python（默认缺失 `venv` 和 `pip` 模块），直接使用单文件免安装的 `uv.exe` 可规避 Python 环境缺失问题。

- **联网工控机一键安装**：
  ```bash
  # 下载并加入当前会话 PATH
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  export PATH="$HOME/.local/bin:$PATH"

  # 创建虚拟环境并安装依赖
  uv venv .venv
  source .venv/Scripts/activate
  uv pip install -e .
  ```

- **离线内网工控机（直接拷贝单文件）**：
  将外网下载的单个 [`uv.exe`](https://github.com/astral-sh/uv/releases) 复制到项目根目录下，直接执行：
  ```bash
  ./uv.exe venv .venv
  source .venv/Scripts/activate
  ./uv.exe pip install -e .
  ```

#### 动态网页探针内核安装 (用于 WES / 调度动态页面抓取)

若现场需要通过 `web_fetch` 抓取并排查调度系统网页（如 DevExpress Blazor Server、Vue、React、ASP.NET WebForms 等动态异步页面），Playwright 依赖独立的 Chromium 运行环境，需执行官方下载指令：

```bash
# 下载并安装 Chromium 浏览器内核
playwright install chromium
```

> [!TIP]
> **内网/弱网加速下载**：若现场工控机访问海外源较慢，可在下载前指定国内镜像源：
> ```powershell
> # Windows PowerShell 环境：
> $env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"
> playwright install chromium
> ```

### 2. 配置文件说明

复制 `config.example.json` 为 `config.json`，配置项目路径与相关服务参数：
```bash
cp config.example.json config.json
```

### 3. 项目认知初始化 (Project Learning)
```bash
# 执行深度项目认知自举
python -m iro_agent.cli init --deep

# 纯静态模式 (无需外部 LLM API)
python -m iro_agent.cli init --deep --static-only
```

### 4. 交互式诊断与网关服务
```bash
# 交互式排查会话
python -m iro_agent.cli chat

# 启动企业协同网关 (如飞书长连接网关)
python -m iro_agent.cli gateway start
```

### 5. 运行工业评测集 (Evaluation)
```bash
# 运行开发评测集
python -m iro_agent.cli eval dev

# 运行回归质量守门评测集
python -m iro_agent.cli eval regression

# 运行外部私有盲测集 (需提供测试集路径)
python -m iro_agent.cli eval external --dataset-dir /path/to/blind_cases
```
评测报告与轨迹回放将自动生成至 `.eval_runs/<run_id>/report.md`。

### 6. 运行全量自动化测试
```bash
pytest -q
```
当前工程包含 138 项针对状态机、证据规划、停止条件、覆盖度学习及评测 Grader 的自动化测试，保持 100% 通过。

### 7. 工控机版本更新与快捷启动

- **工控机拉取更新（推荐命令）**：
  工控机作为生产运行端，为避免历史分叉或文件冲突导致 `git pull` 中断，推荐每次更新时执行以下命令强制对齐远程仓库（本地受 `.gitignore` 保护的 `config.json` 与 `.venv` 不会被覆盖）：
  ```bash
  git fetch origin main && git reset --hard origin/main
  ```

- **Windows 一键交互菜单 (`start_iro_agent.bat`)**：
  在 Windows 下可直接双击运行根目录的 `start_iro_agent.bat`，脚本已将自检、认知自举与日常排查整合为交互式菜单，防止现场误操作。

---

## 目录结构

```text
iro_agent/
├── investigation/              # Investigation Harness
│   ├── harness.py              # 核心闭环驱动引擎
│   ├── state.py                # 动态排查状态机
│   ├── evidence_planner.py     # Next-Best-Evidence 动态规划器
│   ├── priorities.py           # 假设区分增益与动态优先级
│   ├── stop_conditions.py      # 状态驱动停止判定
│   ├── trace.py                # 完整排查轨迹记录
│   └── physical_escalation.py  # 真实物理升级判定
├── evaluation/                 # Evaluation Harness
│   ├── runner.py               # 评测调度执行器
│   ├── dataset.py              # 评测集加载与格式校验
│   ├── scoring.py              # 5 维加权综合评分
│   ├── reporter.py             # 详细评测报告生成器
│   └── graders/                # 确定性、证据锚定、安全与路径质检器
├── knowledge/                  # Project Learning Harness
│   ├── unknowns.py             # Unknown 一等对象与优先级队列
│   ├── learning_state.py       # 10 维知识覆盖度状态
│   ├── learning_loop.py        # 自主多轮学习闭环
│   ├── synthesizer.py          # 认知提炼器 (暴露失败阶段，统一置信度)
│   ├── deep_reader.py          # 定向模块源码深读
│   └── store.py                # 蓝图持久化
├── memory/                     # 记忆与防污染
│   ├── incident_store.py       # 故障经验库 (核验状态区隔)
│   └── learning_store.py       # 运维规则库 (注入防污染溯源元数据)
├── readers/                    # 只读数据源驱动 (Log, Git, DB, WRelease)
├── security/                   # 只读安全与脱敏审计
└── cli.py                      # 统一命令行总入口
```

---

## 许可证

本项目遵循 MIT License 协议。
