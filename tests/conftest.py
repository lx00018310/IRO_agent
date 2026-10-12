import pytest
import json
import zipfile

import iro_agent.config as config_module
from iro_agent.config import IROConfig, SetupState


@pytest.fixture(autouse=True)
def isolated_runtime_storage(tmp_path, monkeypatch):
    """Unit tests never use a workstation's real config, credentials or output paths."""
    monkeypatch.setattr(config_module, "_CONFIG_INSTANCE", IROConfig(project_root=str(tmp_path)))
    monkeypatch.setattr(config_module, "_CONFIG_PATH", tmp_path / "config.json")


@pytest.fixture
def reader_project(tmp_path):
    """Local source/log/release fixtures, independent of TASK-013 on the developer's PC."""
    config = config_module.get_config()
    backend, logs, releases = (tmp_path / name for name in ("backend", "logs", "releases"))
    for path in (backend, logs, releases):
        path.mkdir()
    (backend / "app.py").write_text("database = 'fixture'\n", encoding="utf-8")
    (logs / "service.log").write_text("2026-10-12 10:00:00 ERROR ECONNRESET connection reset\n", encoding="utf-8")
    with zipfile.ZipFile(releases / "v1.wrelease", "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"version": "v1", "createdAt": "2026-10-12T09:00:00",
                                                    "backend": {"sha256": "fixture"}}))
    config.log_dirs = [str(logs)]
    config.wrelease_dir = str(releases)
    return config


@pytest.fixture
def project_config(tmp_path, monkeypatch):
    paths = {name: tmp_path / name for name in ("project", "code_a", "code_b", "logs_a", "logs_b")}
    for path in paths.values():
        path.mkdir()
    config = IROConfig(
        project_name="TEST-PROJECT", project_root=str(paths["project"]),
        sources={
            "code": [{"id": name, "description": name, "path": str(paths[name])} for name in ("code_a", "code_b")],
            "logs": [{"id": name, "description": name, "path": str(paths[name])} for name in ("logs_a", "logs_b")],
            "databases": [{"id": name, "description": name, "host": "127.0.0.1", "user": "readonly",
                           "database": name, "password": "source-secret-" + name} for name in ("db_a", "db_b")],
        },
        glm={"api_key": "unit.test.key"}, feishu={"enabled": False},
        storage={"audit_db_path": "audit.db", "memory_db_path": "memory.db"},
    )
    config.setup = SetupState(version=1, completed_at="2026-10-11T00:00:00+00:00", fingerprint=config.setup_fingerprint())
    monkeypatch.setattr(config_module, "_CONFIG_INSTANCE", config)
    monkeypatch.setattr(config_module, "_CONFIG_PATH", tmp_path / "config.json")
    return config
