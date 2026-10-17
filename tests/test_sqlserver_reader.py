"""SQL Server 只读接入：配置、连接串安全、执行保护、资源释放与方言拦截。"""

import sys
import types
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import ValidationError

import iro_agent.config as config_module
from iro_agent.config import DatabaseConfig, DatabaseSourceConfig, IROConfig, SetupState
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.security.policy import SecurityPolicyError


def sqlserver_config(tmp_path=None, **overrides):
    data = {"type": "sqlserver", "host": "127.0.0.1", "port": 1433, "user": "iro_readonly",
            "password": "unit-secret", "database": "Production", "db_schema": "dbo"}
    data.update(overrides)
    return DatabaseConfig(**data)


def make_reader(tmp_path, db_cfg):
    if tmp_path is not None:
        config_module._CONFIG_INSTANCE = IROConfig(project_root=str(tmp_path))
    return DatabaseReader(db_config=db_cfg)


def install_mock_pyodbc(monkeypatch, connect=None):
    fake = types.ModuleType("pyodbc")
    fake.connect = connect or MagicMock()
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    return fake


# ---------- 配置模型 ----------

def test_default_ports_per_dialect():
    assert DatabaseConfig(type="postgresql").port == 5432
    assert DatabaseConfig(type="mysql").port == 3306
    assert DatabaseConfig(type="sqlserver").port == 1433
    assert DatabaseConfig(type="sqlserver", port=1444).port == 1444


def test_sqlserver_new_fields_and_defaults():
    cfg = sqlserver_config()
    assert cfg.odbc_driver == "ODBC Driver 18 for SQL Server"
    assert cfg.db_schema == "dbo"
    assert cfg.trust_server_certificate is False


def test_odbc_driver_whitelist():
    with pytest.raises(ValidationError):
        DatabaseSourceConfig(id="db", description="d", type="sqlserver", host="h", user="u",
                             database="n", odbc_driver="Some Other Driver")


def test_fingerprint_legacy_pg_mysql_unchanged_by_new_fields(tmp_path):
    old = IROConfig(project_name="P", project_root=str(tmp_path),
                    sources={"databases": [{"id": "db", "description": "d", "type": "postgresql",
                                            "host": "h", "user": "u", "database": "n"}]})
    new = IROConfig(project_name="P", project_root=str(tmp_path),
                    sources={"databases": [{"id": "db", "description": "d", "type": "postgresql",
                                            "host": "h", "user": "u", "database": "n",
                                            "odbc_driver": "ODBC Driver 18 for SQL Server",
                                            "db_schema": "dbo", "trust_server_certificate": False}]})
    assert old.setup_fingerprint() == new.setup_fingerprint()

    mysql_old = IROConfig(project_name="P", project_root=str(tmp_path),
                          sources={"databases": [{"id": "db", "description": "d", "type": "mysql",
                                                  "host": "h", "user": "u", "database": "n"}]})
    mysql_new = IROConfig(project_name="P", project_root=str(tmp_path),
                          sources={"databases": [{**mysql_old.sources.databases[0].model_dump(),
                                                  "odbc_driver": "ODBC Driver 18 for SQL Server"}]})
    assert mysql_old.setup_fingerprint() == mysql_new.setup_fingerprint()

    ss_a = IROConfig(project_name="P", project_root=str(tmp_path),
                     sources={"databases": [{"id": "db", "description": "d", "type": "sqlserver",
                                             "host": "h", "user": "u", "database": "n", "db_schema": "dbo"}]})
    ss_b = IROConfig(project_name="P", project_root=str(tmp_path),
                     sources={"databases": [{"id": "db", "description": "d", "type": "sqlserver",
                                             "host": "h", "user": "u", "database": "n", "db_schema": "sales"}]})
    assert ss_a.setup_fingerprint() != ss_b.setup_fingerprint()

    base = {"id": "db", "description": "d", "type": "sqlserver", "host": "h", "user": "u", "database": "n"}
    a = IROConfig(project_name="P", project_root=str(tmp_path),
                  sources={"databases": [{**base, "trust_server_certificate": False}]})
    b = IROConfig(project_name="P", project_root=str(tmp_path),
                  sources={"databases": [{**base, "trust_server_certificate": True}]})
    assert a.setup_fingerprint() != b.setup_fingerprint()


def test_legacy_setup_completion_survives_upgrade(tmp_path):
    """修改前生成的旧 PG 配置（带旧指纹）升级后仍判定 setup 完成"""
    raw = {"project_name": "P", "project_root": str(tmp_path),
           "sources": {"code": [], "databases": [{"id": "db", "description": "d", "type": "postgresql",
                                                  "host": "h", "port": 5432, "user": "u", "database": "n"}],
                       "logs": [], "http": [], "other": []},
           "glm": {"api_key": "k.t"},
           "setup": {"version": 1, "completed_at": "2026-10-11T00:00:00+00:00", "fingerprint": ""}}
    old_config = IROConfig(**raw)
    old_config.setup.fingerprint = old_config.setup_fingerprint()
    stored = old_config.model_dump()
    # 模拟升级后重新加载：新代码会填充默认新字段，但指纹按 SQL Server 字段排除规则计算
    reloaded = IROConfig(**stored)
    assert reloaded.is_setup_complete()


# ---------- 连接串安全 ----------

def test_connection_string_escapes_and_encrypts():
    reader = make_reader(None, sqlserver_config(password="p;{}w"))
    cs = reader._sqlserver_connection_string()
    assert "PWD={p;{}}w}" in cs
    assert "Encrypt=yes" in cs and "TrustServerCertificate" not in cs
    assert "Server=tcp:{127.0.0.1},1433" in cs


def test_trust_server_certificate_switch():
    reader = make_reader(None, sqlserver_config(trust_server_certificate=True))
    cs = reader._sqlserver_connection_string()
    assert "Encrypt=no;TrustServerCertificate=yes" in cs


def test_nul_or_control_chars_rejected():
    with pytest.raises(ValueError):
        DatabaseReader._odbc_escape("a\x00b")
    with pytest.raises(ValueError):
        reader = make_reader(None, sqlserver_config(user="u\x01ser"))
        reader._sqlserver_connection_string()


# ---------- 执行保护与只读拦截 ----------

def test_explain_rejected_before_connecting(tmp_path, monkeypatch):
    connect = Mock(side_effect=AssertionError("must not connect"))
    install_mock_pyodbc(monkeypatch, connect)
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(SecurityPolicyError, match="EXPLAIN"):
        reader.execute_query("EXPLAIN SELECT 1")
    connect.assert_not_called()


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t WITH (UPDLOCK)",
    "SELECT a FROM OPENROWSET('x','y','z')",
    "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN UPDATE SET a=1",
    "WAITFOR DELAY '00:00:10'",
    "SELECT 1 INTO newtable FROM t",
    "SELECT 1; SELECT 2",
    "SELECT 1\nGO\nDROP TABLE t",
])
def test_sqlserver_specific_writes_are_blocked_before_connection(tmp_path, monkeypatch, sql):
    connect = Mock(side_effect=AssertionError("blocked SQL must not connect"))
    install_mock_pyodbc(monkeypatch, connect)
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(SecurityPolicyError):
        reader.execute_query(sql)
    connect.assert_not_called()


def test_generic_dialect_sql_still_blocked(tmp_path, monkeypatch):
    install_mock_pyodbc(monkeypatch)
    reader = make_reader(tmp_path, sqlserver_config())
    for sql in ("DELETE FROM t", "UPDATE t SET a=1", "INSERT INTO t VALUES (1)", "DROP TABLE t"):
        with pytest.raises(SecurityPolicyError):
            reader.execute_query(sql)


def test_set_rowcount_guard_and_business_sql_not_run_on_guard_failure(tmp_path, monkeypatch):
    cursor = MagicMock()
    cursor.execute.side_effect = [OSError("guard failed"), None]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(RuntimeError, match="未执行"):
        reader.execute_query("SELECT 1", max_rows=7)
    assert cursor.execute.call_count == 1  # 只有保护尝试，业务 SQL 未执行
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


def test_happy_path_rowcount_then_query_never_commits(tmp_path, monkeypatch):
    cursor = MagicMock()
    cursor.description = [("id",), ("name",)]
    cursor.fetchmany.return_value = [(1, "a")]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config())
    rows = reader.execute_query("SELECT id, name FROM task ORDER BY id DESC", max_rows=7)
    assert rows == [{"id": 1, "name": "a"}]
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert executed[0] == "SET ROWCOUNT ?"
    assert "ORDER BY id DESC" in executed[1] and "LIMIT" not in executed[1]
    assert conn.timeout == 10  # query_timeout 默认值
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    cursor.close.assert_called_once()
    conn.close.assert_called_once()


def test_unicode_decimal_null_rows_normalized(tmp_path, monkeypatch):
    import datetime
    from decimal import Decimal
    cursor = MagicMock()
    cursor.description = [("id",), ("name",), ("score",), ("created",), ("memo",)]
    cursor.fetchmany.return_value = [(1, "中文站", Decimal("12.50"),
                                      datetime.datetime(2026, 10, 17, 8, 0, 0), None)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config())
    rows = reader.execute_query("SELECT id, name, score, created, memo FROM t")
    assert rows[0]["name"] == "中文站"
    assert rows[0]["score"] == "12.50"  # Decimal 按 str 截断序列化，与 PG/MySQL 行为一致
    assert rows[0]["created"] == "2026-10-17T08:00:00"
    assert rows[0]["memo"] is None


def test_percent_s_in_sql_string_is_never_rewritten(tmp_path, monkeypatch):
    cursor = MagicMock()
    cursor.description = [("v",)]
    cursor.fetchmany.return_value = [("x",)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config())
    reader.execute_query("SELECT '%s' AS v FROM t")
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert executed[1] == "SELECT '%s' AS v FROM t"


def test_rowcount_cleanup_failure_still_closes(tmp_path, monkeypatch):
    cursor = MagicMock()
    cursor.description = [("id",)]
    cursor.fetchmany.return_value = [(1,)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.execute = Mock(side_effect=OSError("reset failed"))
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config())
    rows = reader.execute_query("SELECT id FROM t")
    assert rows == [{"id": 1}]
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


def test_connection_failure_redacts_password(tmp_path, monkeypatch):
    def bad_connect(_connstr, timeout=None, autocommit=None):
        raise RuntimeError("login failed for user with unit-secret")
    fake = types.ModuleType("pyodbc")
    fake.connect = bad_connect
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(RuntimeError, match="SQL Server 连接失败") as exc_info:
        reader.execute_query("SELECT 1")
    assert "unit-secret" not in str(exc_info.value)


def test_missing_pyodbc_reports_missing_driver(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)  # import pyodbc -> ImportError
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(RuntimeError, match="SQL Server 连接失败"):
        reader.execute_query("SELECT 1")


# ---------- 元数据方言 ----------

def test_default_schema_selection():
    assert make_reader(None, sqlserver_config()).default_schema() == "dbo"
    assert make_reader(None, sqlserver_config(db_schema="sales")).default_schema() == "sales"
    assert make_reader(None, DatabaseConfig(type="mysql", host="h", user="u",
                                            password="p", database="mydb")).default_schema() == "mydb"
    assert make_reader(None, DatabaseConfig(host="h", user="u",
                                            password="p", database="pgdb")).default_schema() == "public"


def test_describe_table_uses_question_mark_placeholders(tmp_path, monkeypatch):
    cursor = MagicMock()
    cursor.description = [("column_name",), ("data_type",), ("is_nullable",),
                          ("column_default",), ("is_primary_key",)]
    cursor.fetchmany.return_value = [("id", "int", "NO", None, 1)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=conn))
    reader = make_reader(tmp_path, sqlserver_config(db_schema="sales"))
    columns = reader.describe_table("task")
    executed = [call.args[0] for call in cursor.execute.call_args_list]
    assert "?" in executed[1] and "%s" not in executed[1]
    assert cursor.execute.call_args_list[1].args[1] == ("sales", "task")
    assert columns[0]["column_name"] == "id"


def test_foreign_keys_unsupported_for_sqlserver(tmp_path):
    reader = make_reader(tmp_path, sqlserver_config())
    with pytest.raises(SecurityPolicyError, match="SQL Server"):
        reader.get_foreign_keys()


# ---------- setup 向导 ----------

def test_wizard_registers_sqlserver_source(tmp_path, monkeypatch):
    from iro_agent.setup import SetupWizard
    for name in ("code_a",):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("TEST_SS_PASS", "ss-secret")
    answers = ["MY-PROJECT", str(tmp_path), "",
               "1", "code_a", "工控代码", f'"{tmp_path / "code_a"}"',
               "2", "db-ss", "工控业务库", "sqlserver", "127.0.0.1", "1433", "Production",
               "iro_readonly", "TEST_SS_PASS", "sales", "", "n",
               "0", "", "", "n", "n", "n", "y"]
    iterator = iter(answers)
    target = tmp_path / "config.json"
    config = SetupWizard(target, input_fn=lambda _: next(iterator), secret_fn=lambda _: "").run()
    db = config.sources.databases[0]
    assert db.type == "sqlserver" and db.db_schema == "sales" and db.port == 1433
    assert db.trust_server_certificate is False
    assert db.password_env == "TEST_SS_PASS" and "ss-secret" not in target.read_text(encoding="utf-8")
    assert config.is_setup_complete()


# ---------- 多来源共存 ----------

def test_sqlserver_and_pg_coexist_via_source_id(tmp_path, monkeypatch):
    from iro_agent.readers.sources import SourceReaders
    ss_conn = MagicMock()
    ss_cursor = MagicMock()
    ss_cursor.description = [("id",)]
    ss_cursor.fetchmany.return_value = [(1,)]
    ss_conn.cursor.return_value = ss_cursor
    install_mock_pyodbc(monkeypatch, MagicMock(return_value=ss_conn))

    import psycopg2
    pg_conn = MagicMock()
    pg_cursor = MagicMock()
    pg_cursor.__enter__.return_value.fetchmany.return_value = [{"id": 2, "dbname": "pgdb"}]
    pg_conn.cursor.return_value = pg_cursor
    monkeypatch.setattr(psycopg2, "connect", MagicMock(return_value=pg_conn))

    config = IROConfig(project_root=str(tmp_path), glm={"api_key": "k.t"},
                       sources={"databases": [
                           {"id": "db-ss", "description": "工控库", "type": "sqlserver", "host": "h",
                            "user": "u", "password": "unit-secret", "database": "Prod"},
                           {"id": "db-pg", "description": "业务库", "type": "postgresql", "host": "h",
                            "user": "u", "password": "unit-secret", "database": "pgdb"}]},
                       storage={"audit_db_path": "audit.db", "memory_db_path": "memory.db"})
    config.setup = SetupState(version=1, completed_at="2026-10-17T00:00:00+00:00",
                              fingerprint=config.setup_fingerprint())
    config_module._CONFIG_INSTANCE = config
    readers = SourceReaders(config)
    output = readers.db_query(sql="SELECT id FROM task")
    assert output["status"] == "OK"
    assert {r["source_id"] for r in output["rows"]} == {"db-ss", "db-pg"}
    ss_conn.commit.assert_not_called()
    pg_conn.rollback.assert_called()


def test_inventory_exposes_schema_but_not_secrets(tmp_path):
    from iro_agent.readers.sources import SourceReaders
    config = IROConfig(project_root=str(tmp_path), glm={"api_key": "k.t"},
                       sources={"databases": [{"id": "db-ss", "description": "工控库", "type": "sqlserver",
                                               "host": "h", "user": "u", "password": "unit-secret",
                                               "database": "Prod", "db_schema": "sales"}]},
                       storage={"audit_db_path": "audit.db", "memory_db_path": "memory.db"})
    inventory = SourceReaders(config).inventory()
    text = repr(inventory)
    assert inventory["sources"][0]["db_schema"] == "sales"
    assert "unit-secret" not in text
