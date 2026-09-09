import tempfile
from pathlib import Path
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.analyzer.timeline import TimelineBuilder
from iro_agent.analyzer.fault_domain import FaultDomainClassifier
from iro_agent.analyzer.impact_scope import ImpactScopeEvaluator
from iro_agent.analyzer.interpreter import BusinessLanguageInterpreter


def test_incident_memory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_memory.db"
        store = IncidentStore(str(db_path))

        inc_id = store.record_incident({
            "incident_id": "INC-20260909-001",
            "symptom": "订单看板卡住无法刷新，WebSocket掉线",
            "user_question": "为什么今天装车显示屏不更新了？",
            "fault_domain": "Network",
            "severity": "P2",
            "confidence": "High",
            "root_cause": "工位 09 网络连接重置 (ECONNRESET)",
        })

        assert inc_id == "INC-20260909-001"
        inc = store.get_incident(inc_id)
        assert inc is not None
        assert inc["fault_domain"] == "Network"

        # 相似查询
        similar = store.find_similar_incidents("WebSocket")
        assert len(similar) == 1

        stats = store.get_similar_incident_stats("WebSocket", days=30)
        assert stats["total_similar_count"] == 1
        assert "Network" in stats["domain_breakdown"]


def test_timeline_builder():
    tb = TimelineBuilder()
    tb.add_event("2026-09-09T08:00:00", "Git", "提交 60450006：修改前端全屏效果", "Git log")
    tb.add_event("2026-09-09T14:28:38", "Log", "后端出现 WebSocket ECONNRESET 掉线", "backend_stdout.log")
    tb.add_event("2026-09-09T09:30:00", "WRelease", "工控机发布 v8.13.6", "manifest.json")

    events = tb.build()
    assert len(events) == 3
    # 验证升序排序
    assert events[0]["timestamp"] == "2026-09-09T08:00:00"
    assert events[1]["timestamp"] == "2026-09-09T09:30:00"
    assert events[2]["timestamp"] == "2026-09-09T14:28:38"

    md = tb.render_markdown()
    assert "| 2026-09-09 08:00:00 | Git |" in md


def test_fault_domain_and_impact():
    domains = FaultDomainClassifier.evaluate(
        symptom="显示屏偶尔掉线",
        recent_release_diff={"has_changes": True, "to_release": "v8.13.6", "changed_modules": [{"module": "backend"}]},
        error_logs=[{"message": "read ECONNRESET", "raw": "read ECONNRESET websocket send failed"}],
    )
    assert "Network" in domains
    assert "Backend" in domains
    assert domains["Network"]["confidence"] in ("High", "Medium")

    impact = ImpactScopeEvaluator.evaluate(
        symptom="装车显示屏提示网络断开，看板刷新延迟",
        fault_domains=domains,
        affected_keywords=["网络断开"],
    )
    assert impact["severity"] == "P2"
    assert "前端看板监控与刷新" in impact["functions_status"]


def test_interpreter_rendering():
    report = BusinessLanguageInterpreter.render_report(
        conclusion="当前故障主要由 09 工位工控网络偶发断开导致，后端主装车逻辑正常。",
        impact_scope={
            "severity": "P2",
            "severity_reason": "仅看板显示延迟，作业未停摆。",
            "functions_status": {"自动装车调度": "正常", "工位看板刷新": "偶发断开"},
        },
        evidence_list=[
            "日志持续记录工位 09 发生 TCP ECONNRESET 连接重置",
            "数据库未发现死锁或超时报错",
        ],
        similar_stats={
            "total_similar_count": 2,
            "period_days": 90,
            "latest_incident_date": "2026-08-29",
            "domain_breakdown": {"Network": 2},
        },
        confidence="High",
    )

    assert "### 1. 诊断结论" in report
    assert "### 2. 业务影响分析 (级别: P2)" in report
    assert "### 3. 关键事实与研判证据" in report
    assert "### 5. 历史相似案例统计" in report
    assert "### 6. 建议现场排查步骤" in report
    assert "### 7. 诊断置信度" in report
