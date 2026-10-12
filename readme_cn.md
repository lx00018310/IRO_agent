# IRO_agent（工业只读诊断 Agent）

> [English](README.md) · **中文**

> **IRO_agent 是一个以证据驱动、严格只读的工业软件诊断 AI Agent。** 它能学习项目的运行模型，通过迭代式证据采集排查事故，并借助可复现的评测数据集对自身诊断质量进行评分。

[![Tests](https://img.shields.io/badge/tests-267%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Security](https://img.shields.io/badge/boundary-Strict%20Read--Only-red.svg)]()

---

## 什么是 IRO_agent？

**IRO_agent**（Industrial Read-Only Agent，工业只读 Agent）是一个用于诊断工业软件系统（如调度系统、生产数据库、服务日志）事故的 AI Agent harness。与通用聊天助手不同，它从不依赖一次性固定步骤推理，而是运行三个相互协作的工业级闭环 **Harness**：

- **Project Learning Harness（项目认知）**——建立「系统到底是什么」的模型。
- **Investigation Harness（排查）**——逐轮采集证据并动态重规划，找出「到底出了什么问题」。
- **Evaluation Harness（评测）**——对诊断本身评分，让质量变得**可度量、可复现**。

每一个结论都必须锚定到具体证据（某行日志、某个配置键、某条数据库记录），并且所有工具对被诊断系统**严格只读**。

| 关键信息 | 内容 |
| :--- | :--- |
| **它是什么** | 一个证据驱动、严格只读的工业诊断 Agent |
| **领域分类** | AI Agent / 工业诊断 / 现场可靠性 / 事故排查 |
| **包名** | `iro-agent`（可通过 `pip install -e .` 安装） |
| **入口命令** | `python -m iro_agent.cli` |
| **Python 版本** | `>= 3.10` |
| **许可证** | MIT |
| **安全边界** | 严格只读——不写文件、不提交 Git、不写业务数据库、不提供任意 Shell |

---

## 适用对象

IRO_agent 面向在生产环境中运行工业 / 本地部署软件系统的团队：

- **工厂 / 运维工程师**：需要在高并发日志噪声下对调度系统、数据库和服务日志进行排障。
- **工业软件维护人员**：维护调度派工系统（如 WES）、ERP / 后端服务，以及机台或设备数据流。
- **内网 / 离线部署**：现场环境可能缺少标准 Python 工具（提供单文件 `uv.exe` 安装路径）。
- **质量与可靠性团队**：需要一种可复现、证据锚定的方式来评估诊断质量。

---

## 核心能力

- **严格只读安全**——对被诊断系统不写文件、不提交 Git、不写业务数据库，也不提供任意 Shell 执行。
- **证据溯源（Evidence Provenance）**——所有推断均需绑定具体日志行、配置键或数据库记录，禁止凭空猜测。
- **逐轮动态重规划**——每轮根据最新证据重新决策下一步，而不是照固定脚本单向前进。
- **竞争假设生命周期**——首轮生成 2~5 个假设，随后在排查过程中增、改、并、弃。
- **可观测性盲区识别**——超时与断连被准确定性为 `OBSERVABILITY_GAP`，而非误判为硬件故障。
- **未知项建模**——业务流盲区、硬件交互不确定性与配置差异被建模为一等对象 `KnowledgeUnknown`。
- **可复现评测**——确定性、证据锚定、安全、路径质量四类 Grader 客观地为每次诊断打分。

---

## 工作原理

| Project Learning Harness（项目认知） | Investigation Harness（排查） | Evaluation Harness（评测） |
| :--- | :--- | :--- |
| • `Unknown` 一等对象 | • 逐轮动态重规划 | • 生产同构 Dispatcher |
| • 10 维知识覆盖度跟踪 | • 竞争假设生命周期状态机 | • 确定性 Grader |
| • 多轮迭代代码精读 | • 事实与因果解耦 | • 证据锚定评分 |
| • 置信度校准与防污染 | • 只读工具安全硬门槛 | • DEV / REGRESSION 库 |

1. **学习（Learn）**——Project Learning Harness 从源码、配置、数据库 Schema 和日志中自举生成项目模型。
2. **排查（Investigate）**——Investigation Harness 逐轮采集证据、检验竞争假设，定位根因。
3. **评测（Evaluate）**——Evaluation Harness 回放每次诊断，用客观的确定性 Grader 打分。

---

## 核心设计理念

工业现场诊断与常规对话 Agent 有根本不同：工业排查面临高并发日志噪声、用户主观误导、时序巧合与物理断电断网等反直觉场景。IRO_agent 放弃了传统的「一次性固定步骤排查」，演进为三大工业级 Harness 闭环系统：

1. **绝对只读安全硬防御（Strict Read-Only）**：对被诊断系统不写文件、不提交 Git、不写业务数据库；诊断工具不提供任意 Shell 执行能力。配置向导仅保存 IRO 自身配置，内部审计、记忆和认知缓存仍由 IRO 管理。双层只读拦截与脱敏审计，严守生产安全底线。
2. **严禁无据断言（Evidence Provenance）**：所有推断均需绑定具体的日志行、配置键或数据库记录，禁止凭空猜测。
3. **真实物理与数字边界划分**：数字观测充分无异常时，支持合法的现场物理排查升级，避免将观测缺口盲目定性为硬件故障。

---

## 核心子系统架构

### 1. Investigation Harness（逐轮动态重规划排查系统）

- **统一运行时分发器（`RuntimeDispatcher`）**：飞书网关、CLI 诊断会话、直接排查命令与基准评测全面归一，故障强制接入 Harness。
- **逐轮重规划引擎（`LLMInvestigationPlanner`）**：每轮基于最新动态证据重新调用大模型决策，严禁固定步骤单向流。
- **权限与 Schema 硬防线（`PlannerValidator`）**：严格校验 JSON Schema、工具只读白名单、入参模型与步数预算，非法操作物理阻断。
- **竞争假设生命周期（`HypothesisManager`）**：支持 2~5 个假设的首轮推演生成及后续增、删、改、并、弃全生命周期流转。
- **事实与因果解耦（`EvidenceEvaluator`）**：区分证据事实抽取与根因推断，超时与断连准确识别为 `OBSERVABILITY_GAP`。

### 2. Project Learning Harness（项目认知学习系统）

- **Unknown 一等对象（`KnowledgeUnknown`）**：显式建模业务流盲区、硬件交互不确定性及配置差异。
- **多维覆盖度量（`LearningState`）**：涵盖架构、模块、业务流、状态机、数据库黄金源等 10 个维度，依据覆盖度收益与优先级自主推进。
- **防污染记忆机制**：历史经验严格作为先验参考（`prior_bias_only`），严禁直接作为当前根因凭证。

### 3. Evaluation Harness（客观评测体系）

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

### 2. 首次运行：必须完成项目配置向导

一个 IRO_agent 实例只管理一个项目；同项目支持多个代码目录、PostgreSQL/MySQL 数据库、日志目录和只读 HTTP 接口。无需先复制示例或手工编辑 JSON：

```powershell
python -m iro_agent.cli setup
```

向导顺序：**项目及工作目录 → 添加多个来源 → 模型及可选飞书凭据 → 校验、脱敏摘要、确认保存**。在来源管理中可反复添加、删除、查看，每种类型都可以有多个来源；不需要的类型可跳过，至少保留一个来源。路径支持中文、空格及带引号的 Windows 路径。输入 `q` 或按 Ctrl+C 取消，`-` 清空可选项；完成前不会覆盖原配置。

未完成向导时，`init`、`chat`、`investigate`、`gateway start`、`eval` 都会阻断并返回非零退出码。`eval` 可能调用真实来源及模型，也需要完成配置。Windows 双击 `start_iro_agent.bat` 会先检查，未完成时自动进入向导。已有旧版 `config.json` 也需要执行一次 `setup`，旧源码、数据库、日志及凭据会导入供确认；当前用户配置不会在升级代码时被自动改写。

以后追加或删除来源，重新运行 `setup` 即可。直接修改项目身份、来源位置或用途会使完成标记失效，必须重新走向导；密码及环境变量凭据值的轮换不改变来源身份。来源变化后旧认知蓝图停止用于查询，运行 `init` 重建即可。帮助、配置查看、自检、来源检查和离线测试（`pytest`）可在配置完成前使用。

```powershell
# 查看来源（不发起现场请求）
python -m iro_agent.cli sources

# 显式检查所有来源：目录检查 / PostgreSQL SELECT 1 / HTTP GET
python -m iro_agent.cli sources --check

# 检查配置流程完成状态
python -m iro_agent.cli setup --check

# 指定配置文件时，--config 放在命令前；一个进程只加载该文件对应的项目
python -m iro_agent.cli --config D:/现场/IRO/config.json setup
```

配置文件默认是**当前目录**的 `config.json`；也可通过 `IRO_CONFIG_PATH` 指定。不会自动读取其他安装目录、旧项目或 `config.example.json`。示例文件仅用于说明配置结构，不代表已完成配置。

数据库密码可以选择环境变量名或隐蔽输入后保存在本机配置中。HTTP 鉴权通过请求头环境变量配置，向导只保存变量名。例如 PowerShell 中：

```powershell
$env:IRO_GLM_API_KEY = "你的模型Key"
$env:ORDERS_DB_PASSWORD = "只读数据库密码"
$env:WES_AUTHORIZATION = "Bearer 你的令牌"
python -m iro_agent.cli setup
```

在数据库来源里填写密码环境变量 `ORDERS_DB_PASSWORD`；在 HTTP 来源里添加请求头 `Authorization`，引用 `WES_AUTHORIZATION`。这些变量应在运行 IRO 的同一个进程环境中设置；临时 PowerShell 变量不会自动传给另一个双击启动的窗口。向导不会把环境变量的凭据值写入 JSON。模型 Key 可跳过以使用 `init --static-only`；在线问答和诊断仍需要有效模型凭据。

查询时模型会收到来源 ID、类型、用途和位置。代码、日志、数据库工具可用 `source_id` 精确选择来源；省略时分别读取该类所有来源，返回结果及失败项均保留来源 ID。例如可提问：「在所有代码目录中查找 dispatch」「分别查看业务库和调度库的任务状态」「只查询 db-wes 的任务表」。数据库支持 PostgreSQL 和 MySQL，跨库查询会分别执行 SQL，不支持跨数据库 SQL JOIN。版本工具继续以第一个代码来源为源码版本源，并保留可选 WRelease 交付版本源。

HTTP 来源登记的是**精确的只读 GET 端点**，包括固定查询参数；不会接受其他 URL、动态追加路径、重定向、浏览器操作或表单登录。多个接口可逐个登记并统一读取。来源检查可在向导中显式跳过；检查失败时，只有明确选择保留才允许保存。运行时部分来源不可用会同时返回已有结果和观测缺口，不会被当作零记录或无异常；故障调查可指定可用来源进一步核实。

### 3. 项目认知初始化 (Project Learning)

```bash
# 执行深度项目认知自举
python -m iro_agent.cli init

# 纯静态模式 (无需外部 LLM API)
python -m iro_agent.cli init --static-only
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
python -m iro_agent.cli eval external --dataset D:/path/to/blind_cases
```

评测报告与轨迹回放将自动生成至 `<project_root>/.iro_agent/.eval_runs/<run_id>/report.md`。

### 6. 运行全量自动化测试

```bash
pytest -q
```

当前本机全量自动化测试为 **267 项通过**，其中本次增加 57 项配置引导、多源读取、来源隔离及回归验证。现场数据源连通性与在线模型服务仍需在实际运行环境中验证。

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
├── runtime/                    # 统一运行时分发系统
│   ├── dispatcher.py           # 企业级统一运行时消息与故障分发器
│   └── models.py               # 路由枚举与分发结果模型
├── investigation/              # Agentic Investigation Harness
│   ├── harness.py              # 逐轮重规划动态排查引擎
│   ├── llm_planner.py          # 结构化 LLM 调查规划器 (带自纠错)
│   ├── planner_validator.py    # Schema、只读权限与预算校验器
│   ├── tool_registry.py        # 统一只读工具注册表与权限白名单
│   ├── hypotheses.py           # 竞争假设推演与生命周期状态机
│   ├── evaluator.py            # 证据事实化提取与可观测性盲区标注
│   ├── state.py                # 动态排查状态机与预算跟踪
│   ├── stop_conditions.py      # 状态驱动确定性停止判定
│   ├── trace.py                # 完整排查轨迹与因果证据溯源
│   └── physical_escalation.py  # 真实物理升级判定与 Guardrail
├── evaluation/                 # Evaluation Harness
│   ├── runner.py               # 生产同构基准评测运行器 (走 RuntimeDispatcher)
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

## 常见问题 (FAQ)

**IRO_agent 是什么？**
IRO_agent（Industrial Read-Only Agent）是一个证据驱动的工业软件诊断 AI Agent。它能学习项目运行模型，通过迭代式证据采集排查事故，并对自身诊断质量进行评分。

**它和普通聊天助手有什么区别？**
它不从一次性固定步骤作答，而是运行 Project Learning、Investigation、Evaluation 三个闭环 Harness；每一轮都基于最新证据重新规划，并要求每个结论都锚定到具体的日志行、配置键或数据库记录。

**在生产系统上运行安全吗？**
安全。它的安全边界是严格只读：对被诊断系统不写文件、不提交 Git、不写业务数据库，也不提供任意 Shell 执行。

**它能诊断哪些系统？**
工业与本地部署软件，例如调度 / 派工系统（如 WES）、PostgreSQL 业务数据库、服务日志，以及动态网页（DevExpress Blazor Server、Vue、React、ASP.NET WebForms）。

**需要联网吗？**
不需要。它支持完全离线 / 内网工控机，通过单文件 `uv.exe` 安装路径即可部署；内网 / 弱网环境还提供 Playwright Chromium 内核的国内镜像加速下载。

**它用的是哪家大模型？**
模型可配置（代码库内置 GLM 客户端，模型凭据可通过环境变量设置）。离线静态自举无需 LLM API，但在线问答与诊断仍需要有效模型凭据。

**诊断质量如何衡量？**
通过 Evaluation Harness，在 DEV、REGRESSION 与私有 BLIND 数据集上，用确定性、证据锚定、安全、路径质量等分层 Grader 客观打分。

**如何快速上手？**
运行 `python -m iro_agent.cli setup` 完成一次性向导，再运行 `python -m iro_agent.cli init` 自举认知；随后用 `chat`、`gateway start`、`eval` 分别进行交互式诊断、企业协同网关与评测。

---

## 许可证

本项目遵循 MIT License 协议。

机器可读元数据（JSON-LD / Schema.org，含规范名称、描述、关键词与 GitHub About/主题标签）见 [`docs/METADATA.json`](docs/METADATA.json)。

[运行写入边界、C# 文本阅读与 MySQL 配置](docs/261012_Readonly_CSharp_MySQL.md)
