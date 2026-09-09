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
│   └── gateway/                  # 外部接入网关
│       └── wechat.py             # 微信网关服务 (@群聊交互、会话保持、安全脱敏回送)
└── tests/                        # 完整测试套件 (20 项单元与端到端场景测试全部通过)
```

---

## 快速上手

### 1. 安装与依赖

```bash
# 创建虚拟环境并安装依赖
uv venv .venv
.venv\Scripts\activate
uv pip install -e .
```

### 2. 配置文件说明 (单一配置文件)

复制 `config.example.json` 为 `config.json`：

> **工控机部署须知**：未来迁移至远程工控机时，**无需改动任何代码**，只需修改 `config.json` 中的各路径、日志地址与数据库连接配置即可。

### 3. 环境自检 (`iro-agent doctor`)

在工控机或本机部署后，执行环境诊断自检：

```bash
iro-agent doctor
```

将依次检查 Python 版本、源码路径、WRelease 发布包、日志目录、Git 仓库只读状态、SQLite 数据库以及 GLM 大模型就绪状态。

### 4. 交互式命令行诊断 (`iro-agent chat`)

```bash
iro-agent chat
```

支持现场提问：
- *"昨天好好的，今天为什么突然卡死了？"*
- *"今天这个升级导致了问题吗？"*
- *"到底哪个模块坏了？现场自动装车还能不能继续跑？"*

### 5. 启动微信网关 (`iro-agent gateway start`)

```bash
# 启动后台网关监听
iro-agent gateway start

# 查看状态
iro-agent gateway status
```

---

## 自动化测试

执行完整测试套件：

```bash
pytest -v
```
