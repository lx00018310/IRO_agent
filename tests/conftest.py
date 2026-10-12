import pytest

import iro_agent.config as config_module
from iro_agent.config import IROConfig, SetupState


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
        storage={"audit_db_path": str(tmp_path / "audit.db"), "memory_db_path": str(tmp_path / "memory.db")},
    )
    config.setup = SetupState(version=1, completed_at="2026-10-11T00:00:00+00:00", fingerprint=config.setup_fingerprint())
    monkeypatch.setattr(config_module, "_CONFIG_INSTANCE", config)
    monkeypatch.setattr(config_module, "_CONFIG_PATH", tmp_path / "config.json")
    return config
