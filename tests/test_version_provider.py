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
    # 如果现场确实没有 current-version.json 指针
    if not status.get("is_running_detected"):
        assert status["confirmed_running_release"] == "UNKNOWN"
        assert status["version"] == "UNKNOWN"
        assert status["pointer_source"] == "unknown"


def test_2_time_correlation_after_update():
    """Test 2: 更新发生于 10:00，首次报错发生于 10:07 -> 判定为发生于更新之后，严禁直接判定为更新导致报错"""
    orch = DiagnosticOrchestrator()
    version_events = [
        {
            "timestamp": "2026-09-10T10:00:00",
            "version_id": "v8.13.6",
            "source_type": "wrelease",
        }
    ]
    first_error_time = "2026-09-10T10:07:00"
    res = orch._analyze_time_correlation(first_error_time, version_events)

    assert res["relationship"] == "Occurred after the version change"
    assert "晚于最近一次版本更新" in res["summary"]
    # 严格证据完整性：禁止无事实推断因果
    assert "时序相关并不等同于因果关系" in res["summary"]
    assert "导致了该异常" not in res["summary"]


def test_3_fault_domain_insufficient_evidence():
    """Test 3: PLC 缺乏证据时，必须评定为 Insufficient evidence，严禁判定为 Mostly ruled out"""
    domains = FaultDomainClassifier.evaluate(
        symptom="订单看板刷新延迟",
        error_logs=[{"message": "WebSocket connection dropped"}],
    )
    assert domains["PLC"]["confidence"] == "Insufficient evidence"
    assert len(domains["PLC"]["evidence"]) == 0


def test_4_impact_scope_default_unknown():
    """Test 4: 历史订单查询功能缺乏证据时，必须为 Unknown，严禁默认 Normal"""
    impact = ImpactScopeEvaluator.evaluate(
        symptom="工位装车看板卡住",
    )
    status_map = impact["functions_status"]
    assert status_map["历史数据与发货清单查询"] == "Unknown"
    assert status_map["PLC 信号互锁与到位检测"] == "Unknown"
    # 核心受影响功能被正确标记
    assert "Affected" in status_map["自动装车/上车调度"]


def test_5_incident_memory_fields_and_provider_integrity():
    """Test 5: 创建故障事件，记忆库持久化必须包含 active_version_provider、timeline_event_ids 与互斥版本"""
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
        # 互斥性检验：WReleaseReader 活跃时，related_git_commits 必须为空列表
        assert record["related_git_commits"] == []
        assert record["timeline_event_ids"] == ["EVT-001", "EVT-002"]


def test_6_resolver_git_first_when_both_valid(monkeypatch):
    """Test 6: Git 与 WRelease 均有效时，默认优先选择 GitReader"""
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: True)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: True)

    reader, name = VersionReaderResolver.resolve()
    assert name == "GitReader"
    assert isinstance(reader, GitReaderAdapter)


def test_7_resolver_wrelease_fallback_when_git_unavailable(monkeypatch):
    """Test 7: Git 不可用但 WRelease 有效时，回退选择 WReleaseReader"""
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: False)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: True)

    reader, name = VersionReaderResolver.resolve()
    assert name == "WReleaseReader"
    assert isinstance(reader, WReleaseReaderAdapter)


def test_8_resolver_none_when_neither_available(monkeypatch):
    """Test 8: 两者均不可用时，active_version_provider 为 None，但诊断流水线仍可基于日志/记忆执行"""
    monkeypatch.setattr(GitReaderAdapter, "is_available", lambda self: False)
    monkeypatch.setattr(WReleaseReaderAdapter, "is_available", lambda self: False)

    reader, name = VersionReaderResolver.resolve()
    assert name == "None"
    assert reader is None

    # 测试在无版本源时诊断编排器不崩溃，依然完成日志与故障定域
    orch = DiagnosticOrchestrator()
    orch.version_reader = None
    orch.active_version_provider = "None"
    res = orch.run_pipeline("物料拒收报错")
    assert res["active_version_provider"] == "None"
    assert "primary_fault_domain" in res
    assert "impact_scope" in res
