# 执行计划：GLM 收口修复与 SQL Server 只读接入

日期：2026-10-17。审查基线：`f93764b2f6ceb2616dbebb105ae39ff6dd9859af`。

此文档交给其他 AI 实施。本轮只生成计划，尚未实现以下功能。

## 1. 目标与范围

只完成两组改动：

1. 修复通用问答 `chat_completion()` 最终汇总无重试、吞错、最后一轮仍可能执行工具的问题。
2. 在现有 PostgreSQL / MySQL 读取链路内增加 SQL Server，覆盖登记、连接检查、查询、表结构和初始化元数据扫描。

遵循最小改动：直接扩展现有类；不引入 ORM、数据库插件架构、通用 SQL 翻译器、新的 Agent 调度层或重试框架。

本次边界：

- SQL Server 首批采用 **TCP 地址 + 固定端口 + SQL 用户名/密码**。默认端口 1433；命名实例可由管理员提供其实际 TCP 端口。Windows 集成认证、LocalDB、自动发现实例/端口不在本次范围。
- SQL Server 默认读取 `dbo`，允许登记一个明确的其他 schema；不自动遍历所有数据库或 schema。
- 不增加 SQLite / Access，不扩展 HTTP POST、动态路径、自动登录或跳转。
- 保持通用问答默认 8 轮及现有 800 输出 token；不修改调查 Harness 的预算和 `complete_structured()` 行为。
- 不增加自动反编译、命令执行、生产库写入或权限管理。
- 保留现有 `.iro_agent` 写入边界、C# 分段阅读、读取上限和来源隔离。
- 只修改代码、测试和必要文档；不修改本机真实 `config.json`，不启动飞书网关，不连接生产库，不安装系统级 ODBC 驱动或部署。Git 提交/推送仅在用户另行要求时执行。

## 2. 已核实的问题与接入点

下列行号基于上述提交；执行前按函数名重新定位。

| 文件 / 位置 | 当前行为 | 本次处理 |
| --- | --- | --- |
| `iro_agent/llm/glm_client.py:367-475` | 主循环重试，最终汇总却单次请求、未检查 HTTP 状态且吞错；最后一轮未阻止工具执行 | 统一本函数两处请求策略，明确收口及失败原因 |
| `iro_agent/llm/glm_client.py:34` | 提示词强制 `ORDER BY ... DESC LIMIT N` | 按来源数据库方言说明最新记录查询 |
| `iro_agent/config.py:11-26` | 仅 `postgresql/mysql`，默认端口有 MySQL 分支 | 增加 `sqlserver` 及必要连接参数 |
| `iro_agent/config.py:217-227` | 初始化指纹使用来源完整 `model_dump()` | 避免新增默认字段使旧 PG/MySQL 项目失效 |
| `iro_agent/setup.py:161-169` | 向导只登记 PG/MySQL | 增加 SQL Server 输入与默认值 |
| `iro_agent/readers/db_reader.py` | 非 MySQL 一律走 PG；使用 `%s`、`LIMIT` 和字典行 | 增加明确 SQL Server 分支、`?` 参数与行映射 |
| `iro_agent/knowledge/schema_scanner.py:43-85` | 默认 public/MySQL 库名；元数据查询写死 `%s` | 适配 dbo/指定 schema 和占位符 |
| `iro_agent/readers/sources.py:75-96,237-258` | 共用 reader，已有来源、失败和脱敏约定 | 沿用；仅补必要的 schema/方言信息 |
| `iro_agent/investigation/tool_registry.py:165` | 工具介绍只写 PG/MySQL | 补 SQL Server 与按来源选择方言的约束 |
| `requirements.txt` / `pyproject.toml` | 无 SQL Server 驱动依赖 | 同步增加 `pyodbc>=5.0.0` |

不要把“网络抖动是现场主要根因”写成事实：尚无现场日志证明。修复的是代码中已确认的失败处理缺口。

## 3. 实施步骤 A：修复通用问答收口

修改 `GlmClient.chat_completion()`，必要时增加一个仅供本函数使用的小私有方法。

### A1. 请求和重试

- 主循环与最终汇总使用同一小段请求逻辑，均调用 `raise_for_status()`。
- 每个请求最多 **3 次总尝试**。仅超时、连接失败、HTTP 429 / 5xx 重试；HTTP 401/403 及其他 4xx 直接失败。
- 两次等待分别为 1 秒、2 秒；最后一次失败后不再 sleep。重试同一 payload，不重放已执行工具。
- 无效 JSON、缺少 `choices/message` 等响应结构错误明确报告；不使用宽泛 `except Exception` 将编程错误无限纳入重试。
- 不把这个改动扩散到 `generate_text()`、`complete_structured()` 或其他 LLM 调用链。

### A2. 最后一轮不得继续执行工具

- 继续沿用现有最后一轮不发送 `tools` 的行为；在本地执行工具前增加 `is_last` 判断。
- 最后一轮若仍返回 `tool_calls`：不执行，不把工具调用意图当成最终答案；进入已有的一次最终汇总阶段。
- 不向历史追加没有对应工具结果的 assistant `tool_calls` 消息，以免下一次 API 请求因消息不配对失败。
- 最终汇总阶段只请求文本，不提供工具，也不执行模型返回的工具调用；失败后结束，不再开启新诊断循环。
- 非最后一轮的正常工具调用、来源标识及 C# 阅读内容传递保持兼容。

### A3. 真实错误与审计

- 去掉最终汇总的 `except: pass`。区分最终请求超时/HTTP 失败、响应格式错误、内容为空及违规继续请求工具。
- 主循环请求失败继续按现有异常约定向调用方报告；最终汇总失败返回简短明确的原因，不再全部归因于“诊断轮次达到上限”。
- 例：`最终汇总请求超时（已尝试 3 次）。`、`已达到问答轮次上限，最终汇总返回空内容。`
- 使用现有 `AuditLogger` 记录阶段、轮次、尝试次数、HTTP 状态及响应携带的 `finish_reason`；字段缺失应能处理。异常文字先脱敏，显式去除 API Key；不记录 Authorization、完整响应正文、工具原文或图片 base64。
- 不盲目复用主循环的 `last_err`；最终汇总应保留自己实际发生的错误。
- 非空回答不因 `finish_reason=length` 被误判为空。长度截断可以记录，暂不据此扩大预算或自动续写。

验收：正常回答不受影响；最终汇总能恢复瞬时故障；永久错误不会无效重试；最后一轮工具 handler 调用次数为零。

## 4. 实施步骤 B：SQL Server 配置与登记

### B1. 配置模型

- `DatabaseConfig.type` 增加统一值 `sqlserver`，不增加多个别名。
- 未填写 port 时，PG / MySQL / SQL Server 分别使用 5432 / 3306 / 1433；显式 port 保持原值。
- 沿用现有 `host/user/password/database/password_env/connect_timeout/query_timeout`；环境变量密码不得写回配置或输出。
- 仅增加三个 SQL Server 参数：`odbc_driver`（默认 `ODBC Driver 18 for SQL Server`）、`db_schema`（默认 `dbo`）、`trust_server_certificate`（默认 `false`）。参数仅对 SQL Server 生效。
- `odbc_driver` 仅允许明确的 Microsoft ODBC Driver 18 / 17 名称；17 只能人工配置，不自动尝试多个驱动。
- 连接固定启用 `Encrypt=yes`；自签名证书场景由用户显式设置 `trust_server_certificate=true`。证书失败不自动关闭加密或跳过验证。[Microsoft 连接参数说明](https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute?view=sql-server-ver17)
- `DatabaseSourceConfig.connection_config()` 必须传递新增字段；旧单库 `database` 配置与新 `sources.databases` 都能使用 SQL Server。
- **兼容旧初始化指纹**：在 `setup_fingerprint()` 中，非 SQL Server 来源排除这三个新增字段，保持其旧摘要输入不变；SQL Server 来源纳入它们。不得通过忽略所有配置变化或自动重写 setup 状态来规避检查。

### B2. Setup 向导

- 类型选择补 `sqlserver`，默认仍为 `postgresql`；端口提示按类型取值。
- 只有 SQL Server 分支询问 schema、ODBC 驱动名称与是否显式信任服务器证书，其他类型的交互顺序不变。
- 连通性检查继续调用现有 `SourceReaders.check()` / `SELECT 1`；失败必须提示真实缺口，不能声称只读权限已验证。
- 缺少 Python 包或已配置 ODBC 驱动时，明确指出缺失项及需要人工安装；Agent 不执行安装器，不回退其他数据库类型或认证方式。

## 5. 实施步骤 C：SQL Server 查询与只读边界

直接扩展 `DatabaseReader`；允许抽出一个 SQL Server 私有执行方法，避免改写 PG/MySQL 已有行为。

### C1. 连接、资源与结果

- 懒加载 `pyodbc`，只有使用 SQL Server 时才导入。
- 连接目标采用 `tcp:host,port`，指定 database、UID/PWD、ODBC driver、加密参数；不接受模型提供任意连接字符串。
- 安全构造 ODBC 字段值，处理分号、花括号等特殊字符并拒绝 NUL/非法控制字符，不能让密码或主机字符串注入额外连接选项。
- `pyodbc.connect(..., timeout=connect_timeout, autocommit=False)`；设置 `conn.timeout=query_timeout` 后再创建执行查询的 cursor。它是 ODBC 查询超时，不能称为与 PG/MySQL 相同的服务端 `statement_timeout`。[pyodbc 超时说明](https://github.com/mkleehammer/pyodbc/wiki/Connection#timeout)
- 根据 `cursor.description` 与行值生成字典，再沿用现有日期、数值和文本序列化；不能对 pyodbc 行直接使用 `dict(row)`。
- 成功和失败均关闭 cursor、rollback、close，任何路径都不得 commit。
- **不能直接复用现有 `with cursor as cur` 包装 pyodbc cursor**：其正常退出会提交事务。使用显式关闭或 `contextlib.closing`，并以测试验证。[pyodbc cursor 上下文行为](https://github.com/mkleehammer/pyodbc/wiki/Cursor#context-manager)

### C2. 行数限制和 SQL

- SQL Server 不使用 `LIMIT` 包装用户查询，避免破坏 T-SQL 的 CTE 和 `ORDER BY`。
- 在同一连接先独立执行内部生成的 `SET ROWCOUNT N`，再执行已通过只读检查的单条 `SELECT` / `WITH ... SELECT`；N 来自现有严格校验的 `max_rows`，仍以 `fetchmany(max_rows)` 限制客户端读取。清理时恢复 `SET ROWCOUNT 0`，避免连接池复用遗留设置；清理失败要记录并继续确保关闭连接，不能覆盖原查询异常。[Microsoft SET ROWCOUNT](https://learn.microsoft.com/en-us/sql/t-sql/statements/set-rowcount-transact-sql?view=sql-server-ver17)
- 设置超时或行数保护失败，停止并报告；不删除保护后重试业务查询。`SET` 由应用内部单独执行，仍禁止模型提交 `SET` 或多语句批次。
- SQL Server 的参数化查询使用 `?`。内部元数据 SQL 按驱动选择占位符；不得对用户 SQL 全局替换 `%s`、`LIMIT` 或字符串内容。
- SQL Server 明确不支持通用工具中的 `EXPLAIN`；返回清晰的“不支持该方言”错误，不执行 SHOWPLAN 设置或额外批次。
- 沿用现有写关键字/多语句拦截；SQL Server 分支补拦 `MERGE`、`WAITFOR`、`OPENROWSET`、`OPENDATASOURCE`、`OPENQUERY`、锁定提示 `UPDLOCK/XLOCK/TABLOCKX/HOLDLOCK` 及批次分隔 `GO`。保留 `INTO`、`EXEC` 等现有拦截，不能为兼容 T-SQL 放宽写入限制。
- 正则检查有误拒绝的可能；本次不写通用 SQL parser，不承诺覆盖全部 T-SQL。拒绝时明确说明，不静默改写后重试。

### C3. 数据库权限边界

- 文档明确要求管理员提供专用只读身份：仅授予目标对象必要 SELECT 和元数据查看权限，不授予业务写、DDL、存储过程执行或服务器管理权限；Agent 不自动建账号、改权限或把业务库设为 READ_ONLY。
- 不将 `readonly=True`、`ApplicationIntent=ReadOnly` 或“结束后 rollback”当成数据库写入隔离。ODBC 的只读属性是提示，规范不要求驱动禁止提交写语句；真正的边界是数据库账号权限。[Microsoft ODBC 只读属性](https://learn.microsoft.com/en-us/sql/odbc/reference/syntax/sqlsetconnectattr-function?view=sql-server-ver17)
- 不增加自动权限修复、通用权限巡检或试写验证流程。现场权限由管理员核验；禁止向生产库发送写 SQL 来证明拦截有效。

## 6. 实施步骤 D：表结构、初始化与模型方言

### D1. 元数据

- SQL Server 的 `list_tables()`、`describe_table()`、`get_foreign_keys()` 和 `SchemaScanner.scan()` 默认使用配置的 `db_schema`；显式传入 schema 时优先使用显式值。PG 仍默认 public，MySQL 仍默认当前数据库。
- 表、字段、主键可沿用 SQL Server 支持的 INFORMATION_SCHEMA 查询，字段值使用 `?` 绑定；主键布尔表达式改为 SQL Server 支持的 `CASE` / bit，不复用 PostgreSQL 的 `true/false`。
- 外键使用正确的目录关联，例如 `sys.foreign_key_columns` 关联表/字段/schema，以外键的列序号配对，避免复合外键错误交叉组合；不得照搬 PG 的 `constraint_column_usage` 查询。
- 返回既有字段名称，元数据别名统一小写；保留 `source_id`、`OK/PARTIAL/UNAVAILABLE`、`observability_gap` 及既有行数上限。
- 沿用现有 `TableMetadata` 结构，不增加索引扫描、存储过程枚举、全实例发现或新知识模型。现有单值 `primary_key` 模型的表达边界应如实说明，不借机重构。
- 初始化必须通过现有 `collect_source_evidence()` 读到 SQL Server 表结构，不能只做到手工 `db_query()` 可用。

### D2. 模型与混合来源

- `SourceReaders.inventory()` 对 SQL Server 暴露 type 和已登记 schema；不暴露驱动凭据、密码或连接字符串。
- 通用提示词改为按 `source_id/type` 选择方言：PG/MySQL 使用 LIMIT；SQL Server 使用 `SELECT TOP (N) ... ORDER BY ... DESC`，必要时先查表结构。
- 工具介绍补 SQL Server；默认调查 Harness 已通过 `ToolRegistry.source_context` 获得来源信息，沿用此链路说明方言，不改变结构化规划协议。
- 多种数据库并存时，要求模型指定 `source_id` 分别查询；不自动将一个 SQL 翻译后广播到不同方言来源。同一方言兼容的已有广播行为无需重写。
- 默认 LLM 调查链路纳入验收。历史确定性 `EvidencePlanner` 有固定业务表名和 LIMIT 模板，本次不改写该旧模板体系；文档标明其并非任意 SQL Server 项目的通用诊断能力。

## 7. 实施步骤 E：必要测试

新增两个聚焦测试文件：`tests/test_glm_chat_finalization.py`、`tests/test_sqlserver_reader.py`；在已有 setup / 多来源测试中补少量兼容用例。

测试使用临时目录、mock HTTP 和 mock pyodbc；不得依赖工作机真实配置、GLM、飞书或生产数据库。mock `time.sleep`，避免真实等待。

### E1. GLM

1. 正常工具后正常回答保持兼容；最终汇总在 Timeout/503 后重试成功，工具不被再次执行。
2. 401/403/400 一次失败结束，429/5xx/连接失败最多三次；最终失败原因正确且日志中不含 API Key。
3. 空 content、`content=None`、非法 JSON、缺失 choices、非空但 `finish_reason=length` 能区分处理。
4. 最后一轮和最终汇总返回 tool_calls 时，handler 均不执行；后续请求历史没有未配对工具消息。
5. 默认轮次仍为 8；不新增无界汇总/续写循环，`complete_structured()` 原测试继续通过。

### E2. SQL Server 与回归

1. 三种数据库默认端口、显式端口、SQL Server 新字段传递、password_env 及向导登记正确；PG/MySQL 原交互兼容。
2. 使用修改前生成的脱敏旧 PG/MySQL 配置与 fingerprint 固定样例，验证升级后仍判定 setup 完成；SQL Server 新增字段的实际变化仍会使其指纹变化。
3. SQL Server 连接与查询超时设置生效；缺驱动、证书失败、超时及行数保护失败均明确报错，业务 SQL 不在保护失败后执行。
4. 行数上限、`SELECT TOP`、`ORDER BY`、`WITH`、`?` 参数、Unicode/日期/Decimal/NULL 结果正常；SQL 字符串中的 `%s` 不被擅自改写；特殊密码不能注入 ODBC 选项。
5. 正常/异常路径都释放资源；禁止直接进入 pyodbc cursor 的事务上下文，commit 次数始终为零；ROWCOUNT 不遗留给后续使用。
6. 写 SQL、SELECT INTO、多语句、危险访问函数/锁提示及 EXPLAIN 在连接前被拒绝；测试不向真实数据库执行这些语句。
7. 列表、字段/主键、外键列配对及 dbo/其他指定 schema 正确；SchemaScanner 与默认 LLM 工具链均能读到结果。
8. SQL Server 与 PG/MySQL 共存时，按 source_id 选对来源；一个来源失败保持 PARTIAL/UNAVAILABLE 和脱敏；现有 MySQL/PG 查询、写入边界、C# 阅读测试不退化。

在 PowerShell 中优先使用现有虚拟环境（依赖缺失时只更新项目虚拟环境）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_glm_chat_finalization.py tests/test_sqlserver_reader.py tests/test_project_setup.py tests/test_multi_source_readers.py tests/test_runtime_read_write_limits.py tests/test_log_db_reader.py
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
git diff --check
git status --short
```

全量测试在本批最终修改后运行一次即可；失败后修复并重跑相关测试。不要宣称历史的“296 passed / 1 skipped”是本次结果。

## 8. 实施步骤 F：文档和交付

- README 的数据库支持列表、向导及查询说明更新，保留其他能力描述。
- 新增简短 SQL Server 使用说明，记录驱动前置条件、三种默认端口、schema、证书处理、只读身份、SQL Server 不支持 EXPLAIN，以及混合数据库须选 source_id。
- `config.example.json` 保持空来源模板；示例放到说明文档，避免登记虚构来源触发真实连接。
- 配置示例（加入实际项目的 `sources.databases`；不要原样写入本机配置）：

```json
{
  "id": "db-sqlserver",
  "description": "工控程序业务数据库",
  "type": "sqlserver",
  "host": "127.0.0.1",
  "port": 1433,
  "database": "Production",
  "db_schema": "dbo",
  "user": "iro_readonly",
  "password_env": "IRO_SQLSERVER_PASSWORD",
  "odbc_driver": "ODBC Driver 18 for SQL Server",
  "trust_server_certificate": false,
  "connect_timeout": 5,
  "query_timeout": 10
}
```

执行 AI 交付时只说明：修改文件、行为变化、实际测试结果、未完成项及现场待验证项。无真实 SQL Server 环境时可以完成 mock 回归，但必须明确标记“SQL Server 实机连接、TLS、权限和查询取消效果尚未验证”；不能据此声称现场验收完成，也不要为缺少服务器临时搭建部署系统。

管理员后续现场核验限于只读操作：确认只读身份与实际版本/端口 → SELECT 1 → 表结构 → 有上限的最新记录查询 → 检查失败提示和来源标识。不得通过修改业务数据来验收。

## 9. 给执行 AI 的起始指令

> 请阅读本计划和仓库当前代码，按 A → B → C → D → E → F 顺序完成最小改动。先检查 git 状态和适用的 AGENTS.md，保留已有修改。不要开启 subagent，不改真实 config.json，不扩展 HTTP/其他数据库，不安装系统驱动，不连接生产环境，不部署或自动提交推送。实现后运行计划列出的必要测试和全量回归，报告真实结果与 SQL Server 实机待验证项；遇到必须增加本计划之外能力才能继续的问题，先指出具体阻塞并等待用户决定，不自行扩大范围。
