# 运行写入边界、C# 文本阅读与 MySQL

## 写入范围与旧配置

`project_root` 是 Agent 自己的工作目录，不应指向工控程序安装目录。生产代码、配置和日志通过现有 `sources` 登记。

运行时内部数据库、认知缓存、飞书图片、评测报告只允许写入 `<project_root>/.iro_agent/`。相对存储路径以此目录为基准；绝对路径必须在此目录内。路径穿越、指向外部的链接/目录联接、不可用的工作目录均报错，不自动切换位置。人工运行 `setup` 保存选定配置文件是独立管理操作，不受运行时输出目录限制。

旧配置若使用了 `.iro_agent` 之外的绝对 `storage.audit_db_path` / `storage.memory_db_path`，请人工改为文件名或允许范围内的绝对路径。默认值如下：

```json
"storage": {
  "audit_db_path": "iro_agent_audit.db",
  "memory_db_path": "iro_agent_memory.db"
}
```

不会自动移动或删除旧数据库。需要保留历史数据时，先停止 Agent，再人工将需要的数据库复制到新目录。评测结果现在位于 `<project_root>/.iro_agent/.eval_runs/`。

使用 Windows 启动脚本会关闭 Python 字节码写入；直接执行 Python 时建议使用 `python -B -m iro_agent.cli ...`。路径检查限制的是应用管理的写入，不替代 Windows 权限：现场仍应使用非管理员运行账号，对生产目录只授予读取权限，Agent 代码与配置也应禁止该账号修改。本次修改不自动创建账号或改动 ACL。

## C# 文本检索和阅读

代码来源的默认文本搜索新增 `.cs`、`.config`、`.csproj`。`code_read` 复用文件读取器，在普通问答和调查模式中均可用：

```json
{"source_id":"code-main","file":"TaskService.cs","start_line":120,"line_count":80}
```

文件必须属于登记的代码来源，返回内容带行号并脱敏。此能力用于已有源码或人工反编译后的文本；不解析 `.exe/.dll`，不增加 C# 调用图或自动反编译工具。

## 基本读取限制

- 单个本地文本文件最多 5,000,000 字节；每个来源一次读取累计最多 20,000,000 字节。
- 单次目录枚举最多 500 个文件、5,000 个条目；超过上限明确报告观测缺口，请缩小来源范围。
- `code_read` 起始行 1–100,000，每次 1–500 行，输出不超过 50,000 字符。
- 代码/日志查询和数据库结果最多 2,000 条。大文件不会自动回退为无界读取；运行日志超过单文件上限时请登记较小的轮转文件目录或先提供有界导出。
- 数据库 `query_timeout` 默认 10 秒，可配置 1–60 秒；PostgreSQL 设置事务内 `statement_timeout`，MySQL 设置会话 `max_execution_time` 和网络读写超时。普通 SELECT 在服务端限制返回行数。

## MySQL 配置

执行 `setup` 添加数据库来源时选择 `mysql`，默认端口 3306；PostgreSQL 保留默认端口 5432。

单个来源的配置示例（地址、库名和账号应替换为现场值）：

```json
{
  "id": "db-mysql",
  "description": "工控程序业务库",
  "type": "mysql",
  "host": "127.0.0.1",
  "port": 3306,
  "database": "production",
  "user": "iro_readonly",
  "password_env": "IRO_MYSQL_PASSWORD",
  "connect_timeout": 5,
  "query_timeout": 10
}
```

安装更新后的项目依赖，包含 `PyMySQL[rsa]`。使用有 `max_execution_time` 支持的 MySQL（5.7.8+ / 8.x）；这不是 MariaDB 适配器。必须提供仅有必要查询权限的数据库账号，不使用 root、FILE 或业务写权限账号。[MySQL 5.7.8 说明](https://dev.mysql.com/doc/relnotes/mysql/5.7/en/news-5-7-8.html)

每次读取在只读事务中执行，最后回滚并关闭连接；超时或只读设置失败就停止，不降级为普通事务。SQL 检查同时拒绝写语句、多语句、文件导出和可覆盖超时的 MySQL 特殊注释。支持查询、列出表、描述表、外键查询和初始化时的 schema 扫描；MySQL schema 默认使用所配置数据库名。

配置/来源改变后需重新完成 `setup`。普通连接测试只验证连通性，不代表现场权限和查询负载验收。
