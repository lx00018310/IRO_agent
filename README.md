# IRO_agent (Industrial Read-Only Agent) V0.1

工业软件只读智能诊断助手。专为工业现场软件设计的证据驱动型根因分析与业务语言解释引擎。

---

## 核心原则

> **Read, search, analyze, remember, explain — 绝不修改生产系统。**

- 系统物理层仅提供只读接口（无写文件、无执行 Shell、无提交 Git、无写 DB 权限）。
- 任何诊断结论必须具备确凿事实链条（Log 报错、WRelease 部署变更指纹、Git 提交记录）。
- 面向现场调度员与项目经理，一律输出脱离底层代码与堆栈的**业务语言诊断报告**。
- **强制依赖 GLM-5.3-Flash**：无伪造降级，未配置有效 API Key 或网络请求失败时坚决报错中断，确保结论完全来自大模型 Tool Calling 与证据推断。

---

## 工程架构

```text
IRO_agent/
├── config.example.json           # 统一配置文件模板 (工控机部署时直接复制并配置实际路径)
├── iro_agent/
│   ├── config.py                 # 全局配置解析器与单例
│   ├── cli.py                    # 命令行总入口 (chat, config, doctor, gateway)
│   ├── security/                 # 安全与只读硬防御
│   │   ├── policy.py             # 目录白名单与写操作拦截
│   │   ├── redactor.py           # 敏感信息脱敏 (密码/Token/私钥)
│   │   └── audit.py              # 私有 SQLite 审计日志
│   ├── readers/                  # 严格只读数据源读取器
│   │   ├── git_reader.py         # 只读 Git 查询 (log/diff/blame/show/status)
│   │   ├── code_reader.py        # 源码安全检索与分片阅读
│   │   ├── wrelease_reader.py    # .wrelease (ZIP) 解析、版本比对与 SHA256 校验
│   │   ├── log_reader.py         # Pino JSON 与文本日志时间窗口检索
│   │   └── db_reader.py          # PostgreSQL SELECT 只读双重拦截客户端
│   ├── memory/                   # 内部记忆库
│   │   └── incident_store.py     # SQLite 故障案例持久化与近 90 天相似事故统计
│   ├── analyzer/                 # 研判内核
│   │   ├── timeline.py           # 跨数据源证据时间线聚合
│   │   ├── fault_domain.py       # 故障域定级 (Frontend/Backend/Network/PLC 等)
│   │   ├── impact_scope.py       # 业务功能受损评估与 P0~P3 定级
│   │   └── interpreter.py        # 业务语言转译报告生成器
│   ├── llm/                      # 大模型层
│   │   └── glm_client.py         # GLM-5.3-Flash API 封装、Tool Calling 与离线研判兜底
│   └── gateway/                  # 外部接入网关 (飞书企业机器人长连接 + 开发适配器)
│       ├── base.py               # 网关抽象适配器与归一化消息结构
│       ├── feishu.py             # 飞书应用机器人生产网关 (WebSocket 长连接、群聊@清洗、图片受控转存)
│       ├── dedup.py              # 事件与消息 SQLite 幂等防重放存储
│       └── http_adapter.py       # 本地开发与测试 HTTP 适配器
└── tests/                        # 完整测试套件 (39 项单元与端到端场景测试全部通过)
```

---

## 快速上手

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

### 2. 配置文件说明 (单一配置文件)

复制 `config.example.json` 为 `config.json`，配置飞书凭据与工程路径：

```json
{
  "project_name": "TASK-013",
  "gateway": {
    "type": "feishu"
  },
  "feishu": {
    "enabled": true,
    "app_id": "cli_xxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
    "bot_name": "IRO_agent",
    "receive_group_at": true,
    "receive_private": true
  }
}
```

> **飞书自建应用配置指引**：
> 1. 前往飞书开放平台创建企业“自建应用”，在“添加应用能力”中开启 **机器人** 能力。
> 2. 开通权限：在“开发配置 -> 权限管理”中开通消息读取、接收群聊与私聊消息、获取图片资源等权限。
> 3. 事件订阅：在“事件订阅”中订阅接收消息事件 `im.message.receive_v1`，模式选择 **WebSocket 长连接**（无需任何公网 IP 或 HTTP 域名解析）。
> 4. 发布应用版本并在飞书内安装生效，将机器人拉入目标工控机运维群。
> 5. 凭证安全：支持通过环境变量 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 注入，系统对凭据实施严格掩码与回送脱敏。

### 3. 环境与网关自检 (`iro-agent gateway doctor`)

在工控机或本机部署后，执行一键健康体检：

```bash
# 全局工控机系统体检
iro-agent doctor

# 飞书网关链路专项体检
iro-agent gateway doctor
```

### 4. 交互式命令行诊断 (`iro-agent chat`)

```bash
iro-agent chat
```

支持现场提问：
- *"昨天好好的，今天为什么突然卡死了？"*
- *"今天这个升级导致了问题吗？"*
- *"到底哪个模块坏了？现场自动装车还能不能继续跑？"*

### 5. 启动飞书机器人网关 (`iro-agent gateway start`)

```bash
# 启动飞书 WebSocket 长连接网关 (生产模式)
iro-agent gateway start

# 启动本地开发测试 HTTP 适配器
iro-agent gateway start --type http

# 查看网关状态
iro-agent gateway status
```

### 6. 工控机版本更新与快捷启动

- **工控机拉取更新（推荐命令）**：
  工控机作为生产运行端，为避免历史分叉或文件冲突导致 `git pull` 中断，推荐每次更新时执行以下命令强制对齐远程仓库（本地被 `.gitignore` 保护的 `config.json` 与 `.venv` 环境不会被覆盖）：
  ```bash
  git fetch origin main && git reset --hard origin/main
  ```

- **Windows 一键交互菜单**：
  在 Windows 下可直接双击运行根目录的 `start_iro_agent.bat`，通过数字菜单直接呼出环境体检、交互对话、网关服务启动等功能。

---

## 自动化测试

执行完整测试套件：

```bash
pytest -v
```
