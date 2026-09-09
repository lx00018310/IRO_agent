import pytest
from pathlib import Path
from iro_agent.config import get_config
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.code_reader import CodeReader
from iro_agent.readers.wrelease_reader import WReleaseReader
from iro_agent.security.policy import SecurityPolicyError


def test_git_reader_task013():
    config = get_config()
    if not Path(config.project_root).exists():
        pytest.skip("TASK-013 物理路径不存在，跳过本地仓库测试")

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
    assert "src_backend" in module_names or "deployment_control" in module_names

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
    assert "modules" in latest

    # 测试比对两个版本
    if len(releases) >= 2:
        ver_b = releases[0]["version"]
        ver_a = releases[1]["version"]
        diff = reader.compare_releases(ver_a, ver_b)
        assert diff["from_release"] == ver_a
        assert diff["to_release"] == ver_b
        assert "changed_modules" in diff
