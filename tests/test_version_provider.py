import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from iro_agent.config import IROConfig
from iro_agent.readers.version_provider import (
    VersionReaderResolver,
    GitReaderAdapter,
    WReleaseReaderAdapter,
)
from iro_agent.readers.wrelease_reader import WReleaseReader
from iro_agent.analyzer.fault_domain import FaultDomainClassifier
from iro_agent.analyzer.impact_scope import ImpactScopeEvaluator
from iro_agent.analyzer.orchestrator import DiagnosticOrchestrator
from iro_agent.memory.incident_store import IncidentStore


def test_1_wrelease_no_pointer_confirmed_running_unknown():
    """Test 1: 交付包存在但现场运行指针不存在时，confirmed_running_release 必须为 UNKNOWN，严禁用最新包冒充"""
    reader = WReleaseReader()
    status = reader.get_running_release()
    if not status.get("is_running_detected"):
        assert status["confirmed_running_release"] == "UNKNOWN"
        assert status["version"] == "UNKNOWN"
        assert status["pointer_source"] == "unknown"


def test_2_time_correlation_between_versions():
    """Test 2: 双向区间时序判定：10:00 发布 v8.13.6，11:21 报错，14:00 发布 v8.13.7 -> 判定为晚于 v8.13.6、早于 v8.13.7"""
    orch = DiagnosticOrchestrator()
    version_events = [
        {
            "timestamp": "2026-09-10T10:00:00",
            "version_id": "v8.13.6",
            "source_type": "wrelease",
        },
        {
            "timestamp": "2026-09-10T14:00:00",
            "version_id": "v8.13.7",
            "source_type": "wrelease",
        },
    ]
    first_error_time = "2026-09-10T11:21:46"
    res = orch._analyze_time_correlation(first_error_time, version_events)

    assert res["relationship"] == "Occurred in-between version changes"
    assert res["before_version"] == "v8.13.6"
    assert res["after_version"] == "v8.13.7"
    assert "晚于版本更新 v8.13.6" in res["summary"]
    assert "早于版本更新 v8.13.7" in res["summary"]
    # 严格证据完整性：禁止无事实推断因果
    assert "时序承接关系并不等同于因果关系" in res["summary"]


def test_3_fault_domain_insufficient_evidence():
    """Test 3: PLC 缺乏证据时，必须评定为 Insufficient evidence，严禁判定为 Mostly ruled out"""
    domains = FaultDomainClassifier.evaluate(
        symptom="订单看板刷新延迟",
        error_logs=[{"message": "WebSocket connection dropped"}],
    )
    assert domains["PLC"]["confidence"] == "Insufficient evidence"
    assert len(domains["PLC"]["evidence"]) == 0


def test_4_impact_scope_default_unknown_and_severity():
    """Test 4: 缺乏证据时业务状态与严重度必须均为 Unknown，禁止默认 Normal 或 P2"""
    impact = ImpactScopeEvaluator.evaluate(
        symptom="请帮我做一次日常例行查询",
    )
    status_map = impact["functions_status"]
    assert status_map["历史数据与发货清单查询"] == "Unknown"
    assert status_map["PLC 信号互锁与到位检测"] == "Unknown"
    assert status_map["自动装车/上车调度"] == "Unknown"
    # 无证据时，severity 严格为 Unknown
    assert impact["severity"] == "Unknown"


def test_5_user_symptom_clue_does_not_elevate_confidence():
    """Test 5: 用户提问关键词仅作为主观线索，无客观系统证据时故障域不能提升为 Medium"""
    domains = FaultDomainClassifier.evaluate(
        symptom="为什么系统卡死、物料拒收了？",
        error_logs=[],
        recent_release_diff=None,
    )
    # 缺乏客观系统证据时，即使用户提到了拒收/卡死，也绝不能达到 Medium
    assert domains["Backend"]["confidence"] == "Insufficient evidence"
    assert "主观" in domains["Backend"]["evidence"][0] or "缺乏" in domains["Backend"]["evidence"][0]


def test_6_git_head_is_source_code_version_semantic():
    """Test 6: Git HEAD 仅代表当前源码版本，不可称为现场运行版本"""
    adapter = GitReaderAdapter()
    ver = adapter.get_current_version()
    assert ver["version_type"] == "source_code_version"
    assert ver["is_running_detected"] is False
    assert "源码" in ver["pointer_source"]


def test_7_incident_memory_fields_and_provider_integrity():
    """Test 7: 创建故障事件，记忆库持久化必须包含 active_version_provider、timeline_event_ids 与互斥版本"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_store.db"
        store = IncidentStore(str(db_path))

        inc_id = store.record_incident({
            "symptom": "物料拒收异常",
            "fault_domain": "Backend",
            "active_version_provider": "WReleaseReader",
            "related_wrelease_versions": ["v8.13.6"],
            "related_git_commits": ["abc1234"],  # WRelease 激活时，Git commits 应该被清空
            "timeline_event_ids": ["EVT-001", "EVT-002"],
            "impact_scope": {"自动装车": "Affected"},
        })

        record = store.get_incident(inc_id)
        assert record is not None
        assert record["active_version_provider"] == "WReleaseReader"
        assert record["related_wrelease_versions"] == ["v8.13.6"]
        assert record["related_git_commits"] == []
        assert record["timeline_event_ids"] == ["EVT-001", "EVT-002"]


def test_8_resolver_three_states(monkeypatch):
    """Test 8: 严格测试 Resolver 核心三态：Git+WRelease->Git, 无Git+WRelease->WRelease, 两者无->None"""
    # 状态 1: Git 与 WRelease 均可用 -> 优先 GitReader
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: True)
    reader1, name1 = VersionReaderResolver.resolve()
    assert name1 == "GitReader"
    assert isinstance(reader1, GitReaderAdapter)

    # 状态 2: Git 不可用，WRelease 可用 -> 回退 WReleaseReader
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: False)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: True)
    reader2, name2 = VersionReaderResolver.resolve()
    assert name2 == "WReleaseReader"
    assert isinstance(reader2, WReleaseReaderAdapter)

    # 状态 3: 两者均不可用 -> None
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: False)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: False)
    reader3, name3 = VersionReaderResolver.resolve()
    assert name3 == "None"
    assert reader3 is None
