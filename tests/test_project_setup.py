import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

import iro_agent.config as config_module
from iro_agent import cli
from iro_agent.config import IROConfig, SourcesConfig, load_config
from iro_agent.setup import SetupWizard, SetupCancelled, atomic_save, masked_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IRO_CONFIG_PATH", raising=False)
    monkeypatch.delenv("IRO_GLM_API_KEY", raising=False)
    monkeypatch.setattr(config_module, "_CONFIG_INSTANCE", None)
    monkeypatch.setattr(config_module, "_CONFIG_PATH", None)


@pytest.mark.parametrize("arguments", [["init", "--static-only"], ["chat"], ["investigate", "test"], ["gateway", "start"], ["eval", "dev"]])
def test_unconfigured_work_commands_are_blocked_before_handlers(arguments, monkeypatch, capsys, tmp_path):
    handler = Mock(side_effect=AssertionError("must never reach runtime"))
    for name in ("cmd_init", "cmd_chat", "cmd_investigate", "cmd_gateway", "cmd_eval"):
        monkeypatch.setattr(cli, name, handler)
    assert cli.main(arguments) == 2
    assert "setup" in capsys.readouterr().out
    handler.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_default_config_never_uses_other_install_or_example(tmp_path):
    config = load_config()
    assert config.project_name == ""
    assert config.database.host == ""
    assert config.sources is None
    assert not config.is_setup_complete()
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "missing.json"))


def test_setup_can_register_two_of_each_kind_and_never_persist_env_values(tmp_path, monkeypatch, capsys):
    for name in ("code_a", "code_b", "logs_a", "logs_b"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("TEST_DB_PASS", "env-database-password")
    monkeypatch.setenv("TEST_HTTP_AUTH", "Bearer env-http-secret")
    answers = ["MY-PROJECT", str(tmp_path), ""]
    for name in ("code_a", "code_b"):
        answers += ["1", name, "后端代码", f'"{tmp_path / name}"']
    for name in ("db_a", "db_b"):
        answers += ["2", name, "业务数据库", "127.0.0.1", "5432", name, "readonly", "TEST_DB_PASS"]
    for name in ("logs_a", "logs_b"):
        answers += ["3", name, "服务日志", str(tmp_path / name)]
    for name in ("http_a", "http_b"):
        answers += ["4", name, "状态查询", "http://127.0.0.1:9999/" + name, "y", "Authorization", "TEST_HTTP_AUTH", "n"]
    answers += ["0", "", "", "n", "n", "n", "y"]
    iterator = iter(answers)
    target = tmp_path / "config.json"
    config = SetupWizard(target, input_fn=lambda _: next(iterator), secret_fn=lambda _: "").run()
    assert config.is_setup_complete()
    assert all(len(getattr(config.sources, kind)) == 2 for kind in ("code", "logs", "databases", "http"))
    assert load_config(str(target)).is_setup_complete()
    stored = target.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    for secret in ("env-database-password", "Bearer env-http-secret"):
        assert secret not in stored
        assert secret not in output
    assert "TEST_DB_PASS" in stored and "TEST_HTTP_AUTH" in stored


def test_repeat_wizard_appends_source_and_preserves_existing_settings(project_config, tmp_path, capsys):
    target = tmp_path / "config.json"
    raw = {**project_config.model_dump(), "custom_setting": "keep-me"}
    target.write_text(json.dumps(raw), encoding="utf-8")
    extra = tmp_path / "extra"
    extra.mkdir()
    answers = iter(["", "", "", "3", "logs_extra", "追加日志", str(extra), "0", "", "", "n", "n", "n", "y"])
    result = SetupWizard(target, input_fn=lambda _: next(answers)).run()
    assert len(result.sources.logs) == 3
    assert result.sources.databases[0].password == "source-secret-db_a"
    assert json.loads(target.read_text(encoding="utf-8"))["custom_setting"] == "keep-me"
    assert "source-secret-db_a" not in capsys.readouterr().out


@pytest.mark.parametrize("exception", [SetupCancelled(), KeyboardInterrupt(), EOFError()])
def test_wizard_cancel_leaves_existing_config_byte_for_byte(project_config, tmp_path, exception):
    target = tmp_path / "config.json"
    original = json.dumps(project_config.model_dump()).encode()
    target.write_bytes(original)

    def stop(_):
        raise exception
    with pytest.raises(type(exception)):
        SetupWizard(target, input_fn=stop).run()
    assert target.read_bytes() == original


def test_wizard_cancel_at_final_confirmation_does_not_create_config(tmp_path):
    answers = iter(["P", str(tmp_path), "", "1", "code", "代码", str(tmp_path), "0", "", "", "n", "n", "n", "n"])
    target = tmp_path / "config.json"
    with pytest.raises(SetupCancelled):
        SetupWizard(target, input_fn=lambda _: next(answers)).run()
    assert not target.exists()


def test_legacy_import_requires_completion_and_preserves_password(tmp_path):
    legacy = IROConfig(project_name="P", project_root=str(tmp_path), log_dirs=[str(tmp_path)],
                       database={"host": "server", "user": "reader", "database": "orders", "password": "legacy-password"})
    sources = SetupWizard.import_legacy(legacy)
    assert len(sources.code) == len(sources.logs) == len(sources.databases) == 1
    assert sources.databases[0].password == "legacy-password"
    assert not legacy.is_setup_complete()


@pytest.mark.parametrize("change", ["project", "path", "description", "remove"])
def test_changed_project_or_sources_blocks_work_again(project_config, tmp_path, monkeypatch, change):
    if change == "project":
        project_config.project_name = "ANOTHER"
    elif change == "path":
        project_config.sources.code[0].path = str(tmp_path)
    elif change == "description":
        project_config.sources.code[0].description = "changed"
    else:
        project_config.sources.databases.pop()
    target = tmp_path / "config.json"
    target.write_text(project_config.model_dump_json(), encoding="utf-8")
    handler = Mock()
    monkeypatch.setattr(cli, "cmd_chat", handler)
    assert cli.main(["-c", str(target), "chat"]) == 2
    handler.assert_not_called()


def test_completed_config_allows_work_handler(project_config, tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    target.write_text(project_config.model_dump_json(), encoding="utf-8")
    handler = Mock(return_value=0)
    monkeypatch.setattr(cli, "cmd_chat", handler)
    assert cli.main(["-c", str(target), "chat"]) == 0
    handler.assert_called_once()


def test_invalid_config_errors_do_not_echo_secret_inputs(tmp_path, capsys):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"sources": {"databases": [{"id": "db", "description": "db", "host": "h",
                       "user": "u", "database": "d", "port": "bad", "password": "private-password"}]}}), encoding="utf-8")
    assert cli.main(["-c", str(target), "chat"]) == 2
    assert "private-password" not in capsys.readouterr().out


def test_duplicate_ids_and_same_directories_are_rejected(tmp_path):
    with pytest.raises(ValidationError, match="ID 重复"):
        SourcesConfig(code=[{"id": "Same", "description": "c", "path": str(tmp_path)}],
                      logs=[{"id": "same", "description": "l", "path": str(tmp_path)}])
    with pytest.raises(ValidationError, match="重复的数据来源"):
        SourcesConfig(code=[{"id": name, "description": name, "path": str(tmp_path)} for name in ("a", "b")])


def test_atomic_save_rejects_concurrent_edit_and_preserves_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="其他程序修改"):
        atomic_save(target, {"new": True}, b"original")
    assert target.read_bytes() == b"changed"


def test_atomic_save_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    target.write_bytes(b"original")
    monkeypatch.setattr("iro_agent.setup.os.replace", Mock(side_effect=OSError("locked")))
    with pytest.raises(OSError):
        atomic_save(target, {"new": True}, b"original")
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".iro-setup-*"))


def test_masked_config_handles_secrets_inside_source_lists():
    raw = {"sources": {"databases": [{"password": "x", "password_env": "DB_PASSWORD"}]}, "glm": {"api_key": "k"}}
    masked = masked_config(raw)
    assert masked["sources"]["databases"][0] == {"password": "********", "password_env": "DB_PASSWORD"}
    assert masked["glm"]["api_key"] == "********"


def test_dispatcher_blocks_incomplete_new_schema_before_model_or_harness(project_config):
    from iro_agent.runtime.dispatcher import RuntimeDispatcher
    from iro_agent.setup import SetupRequiredError
    project_config.setup.fingerprint = ""
    harness, client = Mock(), Mock()
    dispatcher = RuntimeDispatcher(config=project_config, harness=harness, glm_client=client, learning_store=Mock())
    with pytest.raises(SetupRequiredError):
        dispatcher.dispatch("列出数据来源")
    harness.investigate.assert_not_called()
    client.chat_completion.assert_not_called()


def test_all_sources_removed_cannot_be_marked_complete(project_config):
    project_config.sources = SourcesConfig()
    project_config.setup.fingerprint = project_config.setup_fingerprint()
    assert not project_config.is_setup_complete()


@pytest.mark.parametrize("keep_unavailable", [False, True])
def test_failed_connectivity_requires_explicit_choice_before_save(project_config, tmp_path, monkeypatch, keep_unavailable):
    from iro_agent.readers.sources import SourceReaders
    target = tmp_path / "config.json"
    original = project_config.model_dump_json().encode()
    target.write_bytes(original)
    monkeypatch.setattr(SourceReaders, "check", lambda _: [{"source_id": "db_a", "status": "UNAVAILABLE", "error": "offline"}])
    answers = iter(["", "", "", "0", "", "", "n", "n", "y", "y" if keep_unavailable else "n", "y"])
    wizard = SetupWizard(target, input_fn=lambda _: next(answers))
    if keep_unavailable:
        assert wizard.run().is_setup_complete()
    else:
        with pytest.raises(SetupCancelled):
            wizard.run()
        assert target.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows batch entry point")
def test_windows_launcher_forces_wizard_and_preserves_cancel_exit_code(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    target = tmp_path / "new-config.json"
    env = {**os.environ, "IRO_CONFIG_PATH": str(target)}
    result = subprocess.run(["cmd.exe", "/d", "/c", str(repo / "start_iro_agent.bat"), "chat"],
                            input="q\n", text=True, encoding="utf-8", errors="replace", capture_output=True,
                            cwd=repo, env=env, timeout=45)
    assert result.returncode == 2
    assert "配置引导" in result.stdout
    assert "配置向导" in result.stdout
    assert not target.exists()


def test_missing_project_workdir_blocks_before_runtime(project_config, tmp_path, monkeypatch):
    Path(project_config.project_root).rmdir()
    target = tmp_path / "config.json"
    target.write_text(project_config.model_dump_json(), encoding="utf-8")
    handler = Mock()
    monkeypatch.setattr(cli, "cmd_chat", handler)
    assert cli.main(["-c", str(target), "chat"]) == 2
    handler.assert_not_called()
