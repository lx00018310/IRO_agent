from typing import Dict, Any, List, Optional
from iro_agent.config import get_config
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.version_provider import VersionReaderResolver, VersionReader
from iro_agent.readers.log_reader import LogReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.analyzer.timeline import TimelineBuilder
from iro_agent.analyzer.fault_domain import FaultDomainClassifier
from iro_agent.analyzer.impact_scope import ImpactScopeEvaluator
from iro_agent.analyzer.interpreter import BusinessLanguageInterpreter


class DiagnosticOrchestrator:
    """
    诊断编排器：双版本提供者与时间轴证据完整性核心调度器。
    严格遵循：
    1. 动态确定唯一的活跃版本提供者 (Git 优先，WRelease 兜底)。
    2. 基于时间轴融合日志、版本与现场提问。
    3. 时序相关 != 因果关系，客观判定前后时间关系。
    """

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        prefer_provider: Optional[str] = None,
    ):
        self.config = get_config()
        self.audit = audit_logger or AuditLogger()
        self.version_reader, self.active_version_provider = VersionReaderResolver.resolve(
            config=self.config,
            audit_logger=self.audit,
            prefer_provider=prefer_provider,
        )
        self.log_reader = LogReader(audit_logger=self.audit)
        self.db_reader = DatabaseReader(db_config=self.config.database, audit_logger=self.audit)
        self.memory_store = IncidentStore()

    def run_pipeline(
        self,
        symptom: str,
        log_keyword: Optional[str] = None,
        max_logs: int = 15,
        user_message_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """端到端执行证据采集、时序对齐、故障定域与影响面计算"""
        tb = TimelineBuilder(project_name=self.config.project_name)

        # 1. 采集活跃版本提供者的版本事件与运行状态
        running_ver_info = None
        recent_release_diff = None
        version_events = []
        if self.version_reader:
            running_ver_info = self.version_reader.get_current_version()
            version_events = self.version_reader.get_version_events()

            # 将版本变动写入统一时间轴
            for ve in version_events[:5]:
                tb.add_event(
                    timestamp=ve["timestamp"],
                    source=ve["source_type"],
                    event=f"版本事件 [{ve['version_id']}]: {ve['description']}",
                    evidence=f"提供者: {self.active_version_provider}",
                    is_confirmed=True,
                    event_type=ve.get("event_type", "version_change"),
                )

            # 比对最近两个版本的变动
            recent_vers = self.version_reader.get_recent_versions(limit=2)
            if len(recent_vers) >= 2:
                try:
                    ver_b = recent_vers[0].get("version") or recent_vers[0].get("commit")
                    ver_a = recent_vers[1].get("version") or recent_vers[1].get("commit")
                    if ver_a and ver_b:
                        recent_release_diff = self.version_reader.compare_versions(ver_a, ver_b)
                except Exception:
                    pass

        # 2. 采集日志报错
        search_kw = log_keyword or (symptom.split()[0] if symptom else None)
        logs = self.log_reader.search_logs(keyword=search_kw, level="ERROR", max_results=max_logs)
        if not logs and search_kw:
            # 业务拒收或异常提示在日志中常作为 INFO/WARN 业务响应返回，自动回退全级别匹配
            logs = self.log_reader.search_logs(keyword=search_kw, level=None, max_results=max_logs)
        first_error_time = None
        latest_error_time = None

        for lg in logs[:10]:
            ts = lg.get("time") or lg.get("timestamp") or ""
            if ts:
                if not first_error_time or ts < first_error_time:
                    first_error_time = ts
                if not latest_error_time or ts > latest_error_time:
                    latest_error_time = ts
            msg = lg.get("message") or lg.get("raw") or "日志异常"
            tb.add_event(
                timestamp=ts,
                source="Log",
                event=msg[:80],
                evidence=f"来源: {lg.get('source_file', 'unknown')}",
                is_confirmed=True,
                event_type="error_log",
            )

        # 3. 记录会话时间至时间轴
        if user_message_time:
            tb.add_conversation_event(
                timestamp=user_message_time,
                role="user",
                message=symptom,
            )

        timeline_events = tb.build()

        # 4. 分析时序关联性 (判定异常发生在版本变化之前还是之后)
        time_correlation = self._analyze_time_correlation(first_error_time, version_events)

        # 5. 故障域判定 (严格遵循无证据评定为 Insufficient evidence)
        fault_domains = FaultDomainClassifier.evaluate(
            symptom=symptom,
            recent_release_diff=recent_release_diff,
            error_logs=logs,
        )

        # 6. 业务影响面评估 (严格默认 Unknown)
        impact = ImpactScopeEvaluator.evaluate(
            symptom=symptom,
            fault_domains=fault_domains,
            affected_keywords=[symptom],
        )

        # 7. 历史相似度统计
        similar_stats = self.memory_store.get_similar_incident_stats(search_kw or symptom[:20], days=90)

        # 8. 提炼核心结论与证据链
        top_domains = [d for d, val in fault_domains.items() if val.get("confidence") in ("High", "Medium")]
        primary_domain = top_domains[0] if top_domains else "Unknown"

        evidence_list = []
        evidence_list.append(f"当前活跃版本源: {self.active_version_provider}")
        if running_ver_info:
            v_type = running_ver_info.get("version_type", "running_release")
            c_ver = running_ver_info.get("confirmed_running_release") or running_ver_info.get("version") or "UNKNOWN"
            if v_type == "source_code_version":
                evidence_list.append(f"当前源码版本: {c_ver} (来源: {running_ver_info.get('pointer_source', 'Git HEAD')})")
            else:
                evidence_list.append(f"现场运行版本: {c_ver} (指针来源: {running_ver_info.get('pointer_source', '未知')})")
        if time_correlation.get("summary"):
            evidence_list.append(f"时序分析: {time_correlation['summary']}")
        if logs:
            evidence_list.append(f"捕获到 {len(logs)} 条关联运行报错 (首次报错时间: {first_error_time or '未知'})")

        # 9. 沉淀结构化数据至故障记忆库 (单点写入)
        inc_id = self.memory_store.record_incident({
            "symptom": symptom[:100],
            "fault_domain": primary_domain,
            "severity": impact.get("severity", "Unknown"),
            "confidence": fault_domains.get(primary_domain, {}).get("confidence", "Medium"),
            "impact_scope": impact.get("functions_status", {}),
            "related_logs": [lg.get("message", "")[:100] for lg in logs[:5]],
            "related_git_commits": [ve["version_id"] for ve in version_events if ve["source_type"] == "git"],
            "related_wrelease_versions": [ve["version_id"] for ve in version_events if ve["source_type"] == "wrelease"],
            "active_version_provider": self.active_version_provider,
            "timeline_event_ids": [e["event_id"] for e in timeline_events],
        })

        return {
            "incident_id": inc_id,
            "symptom": symptom,
            "active_version_provider": self.active_version_provider,
            "primary_fault_domain": primary_domain,
            "fault_domains": fault_domains,
            "impact_scope": impact,
            "timeline": timeline_events,
            "time_correlation": time_correlation,
            "similar_stats": similar_stats,
            "evidence_list": evidence_list,
            "running_release": running_ver_info,
            "release_diff": recent_release_diff,
        }

    def _analyze_time_correlation(
        self, first_error_time: Optional[str], version_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        严格评估首次异常时间与版本变动的双向区间时序关系：
        精确定位异常发生前最近的版本 (before_event) 与异常发生后最近的版本 (after_event)。
        禁止无直接事实证据直接推断因果关系。
        """
        if not first_error_time or not version_events:
            return {
                "relationship": "Insufficient evidence",
                "summary": "缺乏确凿的版本更新时间或首次报错时间戳，无法确定时序先后关系。",
                "first_error_time": first_error_time,
                "before_version": None,
                "after_version": None,
            }

        first_err_clean = first_error_time[:19].replace("_", " ").replace("T", " ")

        # 归一化并按时间升序排序
        def _get_ts(v):
            return str(v.get("timestamp", ""))[:19].replace("_", " ").replace("T", " ")

        sorted_vers = sorted(version_events, key=_get_ts)

        before_event = None
        after_event = None

        for ve in sorted_vers:
            vt = _get_ts(ve)
            if not vt:
                continue
            if vt <= first_err_clean:
                before_event = ve
            elif vt > first_err_clean and after_event is None:
                after_event = ve

        before_ver_id = before_event.get("version_id") if before_event else None
        before_ver_time = _get_ts(before_event) if before_event else None
        after_ver_id = after_event.get("version_id") if after_event else None
        after_ver_time = _get_ts(after_event) if after_event else None

        if before_event and after_event:
            rel = "Occurred in-between version changes"
            summary = (
                f"首次报错发生于 {first_err_clean}：晚于版本更新 {before_ver_id} ({before_ver_time})，"
                f"早于版本更新 {after_ver_id} ({after_ver_time})。"
                f"异常发生在 {before_ver_id} 运行周期内（注：时序承接关系并不等同于因果关系，需结合调用链确认）。"
            )
        elif before_event and not after_event:
            rel = "Occurred after the version change"
            summary = (
                f"首次报错发生于 {first_err_clean}：晚于最近一次版本更新 {before_ver_id} ({before_ver_time})。"
                f"存在时间上的先后承接关系（注：时序相关并不等同于因果关系）。"
            )
        elif not before_event and after_event:
            rel = "Occurred before the version change"
            summary = (
                f"首次报错发生于 {first_err_clean}：早于后续版本更新 {after_ver_id} ({after_ver_time})。"
                f"该异常在 {after_ver_id} 发布前即已存在。"
            )
        else:
            rel = "Insufficient evidence"
            summary = "无法建立有效的时间区间比对。"

        return {
            "relationship": rel,
            "summary": summary,
            "first_error_time": first_err_clean,
            "before_version": before_ver_id,
            "before_version_time": before_ver_time,
            "after_version": after_ver_id,
            "after_version_time": after_ver_time,
        }
