import tempfile
import pytest
from pathlib import Path
from iro_agent.config import IROConfig
from iro_agent.security import (
    validate_read_path,
    assert_read_only_operation,
    SecurityPolicyError,
    redact_secrets,
    AuditLogger,
)


def test_validate_read_path_allowed():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test.log"
        test_file.write_text("test content", encoding="utf-8")

        config = IROConfig(
            project_root=tmp_dir,
            wrelease_dir="",
            log_dirs=[],
            allowed_paths=[tmp_dir],
        )

        resolved = validate_read_path(test_file, config)
        assert resolved == test_file.resolve()


def test_validate_read_path_forbidden():
    with tempfile.TemporaryDirectory() as tmp_dir1, tempfile.TemporaryDirectory() as tmp_dir2:
        config = IROConfig(
            project_root=tmp_dir1,
            wrelease_dir="",
            log_dirs=[],
            allowed_paths=[tmp_dir1],
        )
        forbidden_file = Path(tmp_dir2) / "secret.txt"
        forbidden_file.write_text("secret", encoding="utf-8")

        with pytest.raises(SecurityPolicyError):
            validate_read_path(forbidden_file, config)


def test_validate_read_path_traversal():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = IROConfig(
            project_root=tmp_dir,
            wrelease_dir="",
            log_dirs=[],
            allowed_paths=[tmp_dir],
        )
        traversal_path = Path(tmp_dir) / ".." / ".." / "Windows" / "System32"

        with pytest.raises(SecurityPolicyError):
            validate_read_path(traversal_path, config)


def test_assert_read_only_operation():
    assert_read_only_operation("read_log")
    assert_read_only_operation("search_code")
    assert_read_only_operation("git_log")

    with pytest.raises(SecurityPolicyError):
        assert_read_only_operation("git_commit")

    with pytest.raises(SecurityPolicyError):
        assert_read_only_operation("delete_file")

    with pytest.raises(SecurityPolicyError):
        assert_read_only_operation("update_db")


def test_redact_secrets():
    raw_text = "db connection: postgresql://admin:SuperSecret123@10.0.0.1:5432/db, api_key: sk-1234567890abcdef, password = mypwd!"
    redacted = redact_secrets(raw_text)

    assert "SuperSecret123" not in redacted
    assert "sk-1234567890abcdef" not in redacted
    assert "mypwd!" not in redacted
    assert "REDACTED_DB_PASSWORD" in redacted
    assert "REDACTED_SECRET" in redacted
    assert "REDACTED_PASSWORD" in redacted


def test_audit_logger():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "audit.db"
        logger = AuditLogger(str(db_path))

        row_id = logger.record(
            tool_name="LogReader",
            operation="read_log",
            target="/path/to/log password=123456",
            result_summary="Found 1 error",
            status="SUCCESS",
        )
        assert row_id > 0

        recent = logger.query_recent(10)
        assert len(recent) == 1
        assert recent[0]["tool_name"] == "LogReader"
        assert "123456" not in recent[0]["target"]
        assert "REDACTED_PASSWORD" in recent[0]["target"]
