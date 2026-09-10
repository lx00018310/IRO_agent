import pytest
from pathlib import Path
from iro_agent.config import get_config
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.code_reader import CodeReader
from iro_agent.readers.wrelease_reader import WReleaseReader
from iro_agent.security.policy import SecurityPolicyError


def test_git_reader_task013():
    config = get_config()
    if not Path(config.project_root).exists() or not (Path(config.project_root) / ".git").exists():
        pytest.skip("TASK-013 Git 仓库不存在（工控机纯交付部署环境），跳过本地 Git 测试")

    reader = GitReader()
    commits = reader.get_recent_commits(limit=5)
    assert len(commits) > 0
    assert "commit" in commits[0]
    assert "summary" in commits[0]

    # 测试安全拦截：禁止 git commit / checkout
    with pytest.raises(SecurityPolicyError):
        reader._run_git_readonly(["commit", "-m", "test"])


def test_code_reader_task013():
    config = get_config()
    if not Path(config.project_root).exists():
        pytest.skip("TASK-013 物理路径不存在，跳过代码测试")

    reader = CodeReader()
    modules = reader.list_modules()
    assert len(modules) > 0
    module_names = [m["name"] for m in modules]
    assert any(m in module_names for m in ["src_backend", "deployment_control", "backend", "controller", "face_isup"])

    # 检索代码
    results = reader.search_code("database", max_results=5)
    assert len(results) > 0
    assert "file" in results[0]


def test_wrelease_reader_task013():
    config = get_config()
    if not Path(config.wrelease_dir).exists():
        pytest.skip("WRelease 物理路径不存在，跳过测试")

    reader = WReleaseReader()
    releases = reader.list_available_releases()
    assert len(releases) > 0

    latest = reader.get_latest_release()
    assert latest is not None
    assert "version" in latest
    assert "modules_summary" in latest

    # 测试比对两个版本
    if len(releases) >= 2:
        ver_b = releases[0]["version"]
        ver_a = releases[1]["version"]
        diff = reader.compare_releases(ver_a, ver_b)
        assert diff["from_release"] == ver_a
        assert diff["to_release"] == ver_b
        assert "changed_modules" in diff

    # 测试运行版本探测 (严格遵守证据完整性：区分最新可用包与已确认运行版本)
    running = reader.get_running_release()
    assert running is not None
    assert "is_running_detected" in running
    assert "confirmed_running_release" in running

    summary = reader.get_release_status_summary()
    assert "latest_available_release" in summary
    assert "confirmed_running_release" in summary


