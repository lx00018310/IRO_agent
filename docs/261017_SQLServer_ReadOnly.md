# SQL Server 只读接入（261017）

在 PostgreSQL / MySQL 之外，`sources.databases` 现在支持 `type: "sqlserver"`，走同一条只读查询链路（`db_query` / `db_describe` / 初始化 schema 扫描）。

## 前置条件（人工安装，Agent 不自动安装）

1. Python 包：`pip install pyodbc>=5.0.0`（或重跑 `pip install -e .`）。
2. Microsoft ODBC Driver：默认要求 **ODBC Driver 18 for SQL Server**；如现场只有 17，在配置中把 `odbc_driver` 手工改为 `ODBC Driver 17 for SQL Server`。不会自动尝试多个驱动。
3. 数据库账号：使用**专用只读身份**，仅授予目标对象的必要 SELECT 与元数据查看权限；不授予业务写、DDL、存储过程执行或服务器管理权限。Agent 不建账号、不改权限。

## 配置

`setup` 向导选择数据库类型 `sqlserver` 即可，或直接在 `sources.databases` 中登记（示例，加入实际项目配置，不要写进 `config.example.json`）：

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

- 三种数据库默认端口：PostgreSQL 5432 / MySQL 3306 / SQL Server 1433；显式填写的端口保持原值。
- `db_schema` 默认 `dbo`；元数据扫描与 `db_describe` 都按它过滤。其他类型不受影响（PG 仍默认 `public`，MySQL 仍默认数据库名）。
- `odbc_driver` / `db_schema` / `trust_server_certificate` 三个字段仅对 SQL Server 生效；对 PG/MySQL 项目，升级不会改变 setup 指纹，旧配置无需重新 `setup`。
- 密码建议用环境变量（`password_env`），向导不会把明文写进配置。

## 加密与证书

连接固定 `Encrypt=yes`（Driver 18 默认）。服务器使用自签名证书时，请管理员评估后显式设置 `"trust_server_certificate": true`（此时连接为 `Encrypt=no; TrustServerCertificate=yes`）；Agent 不会自动关闭加密或跳过验证。

## 查询方言与限制

- 行数上限通过内部 `SET ROWCOUNT N` 实现，用户 SQL 原样执行（不包 `LIMIT`，兼容 CTE 与 `ORDER BY`）。
- 仅允许单条 `SELECT` / `WITH ... SELECT`；参数占位符为 `?`。额外拦截 `MERGE`、`WAITFOR`、`OPENROWSET/OPENDATASOURCE/OPENQUERY`、锁提示（`UPDLOCK/XLOCK/TABLOCKX/HOLDLOCK`）与 `GO` 批次；`EXEC/EXECUTE/INTO` 等沿用全局拦截。
- **不支持 `EXPLAIN`**（SQL Server 方言），请求将直接报错，不执行 SHOWPLAN。
- `get_foreign_keys` 对 SQL Server 明确返回不支持；表结构请用 `db_describe`。
- 超时为 ODBC 查询超时（`conn.timeout`），不是 PG/MySQL 的服务端 `statement_timeout`。
- 正则拦截可能误拒个别合法 T-SQL；被拒时会如实报错，不会静默改写重试。真正的写入隔离由数据库账号权限保证，不依赖只读连接属性。

## 混合数据库

同一项目可同时登记 PostgreSQL / MySQL / SQL Server 来源。查询时用 `source_id` 精确选择来源；跨库不支持 JOIN，也不会自动把一条 SQL 翻译后广播到不同方言。按来源类型选用最新记录写法：PG/MySQL 用 `ORDER BY ... DESC LIMIT N`；SQL Server 用 `SELECT TOP (N) ... ORDER BY ... DESC`。

## 旧配置兼容

升级后旧 PG/MySQL 项目的 `setup` 完成状态与指纹不变；只有 SQL Server 来源的这三个字段变化才会触发指纹变化（需要重新 `setup` 确认）。

## 现场验证清单（只读操作）

确认只读身份与实际版本/端口 → `SELECT 1` → 表结构 → 有上限的最新记录查询 → 检查失败提示与来源标识。不得通过修改业务数据验收。
