from typing import Dict, Any, List, Optional
from iro_agent.config import get_config
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.wrelease_reader import WReleaseReader
from iro_agent.readers.log_reader import LogReader
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.analyzer.timeline import TimelineBuilder
from iro_agent.analyzer.fault_domain import FaultDomainClassifier
from iro_agent.analyzer.impact_scope import ImpactScopeEvaluator
from iro_agent.analyzer.interpreter import BusinessLanguageInterpreter


class DiagnosticOrchestrator:
    """诊断编排器：端到端调度读取器、时间线聚合、故障域判定、业务影响评估与业务语言解释"""

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.config = get_config()
        self.audit = audit_logger or AuditLogger()
        self.git_reader = GitReader(audit_logger=self.audit)
        self.wrelease_reader = WReleaseReader(audit_logger=self.audit)
        self.log_reader = LogReader(audit_logger=self.audit)
        self.memory_store = IncidentStore()

    def run_pipeline(
        self,
        symptom: str,
        log_keyword: Optional[str] = None,
        max_logs: int = 15,
    ) -> Dict[str, Any]:
        """端到端执行证据采集、时序对齐、故障定域与影响面计算"""
        tb = TimelineBuilder()

        # 1. 采集 WRelease 变动
        running_rel = self.wrelease_reader.get_running_release()
        all_rels = self.wrelease_reader.list_available_releases()
        rel_diff = None
        if len(all_rels) >= 2:
            try:
                rel_diff = self.wrelease_reader.compare_releases(all_rels[1]["version"], all_rels[0]["version"])
            except Exception:
                pass

        if running_rel and running_rel.get("created_at"):
            tb.add_event(
                timestamp=running_rel["created_at"],
                source="WRelease",
                event=f"生产环境运行版本: {running_rel['version']}",
                evidence=f"指针来源: {running_rel.get('pointer_source', '默认')}",
            )

        # 2. 采集 Git 提交
        commits = self.git_reader.get_recent_commits(limit=5)
        for c in commits:
            tb.add_event(
                timestamp=c["date"][:19],
                source="Git",
                event=f"提交 {c['commit'][:8]}: {c['summary']}",
                evidence=f"作者: {c['author']}",
            )

        # 3. 采集日志报错
        search_kw = log_keyword or (symptom.split()[0] if symptom else None)
        logs = self.log_reader.search_logs(keyword=search_kw, level="ERROR", max_results=max_logs)
        for lg in logs[:8]:
            ts = lg.get("time") or lg.get("timestamp") or "未知时间"
            msg = lg.get("message") or lg.get("raw") or "日志异常"
            tb.add_event(
                timestamp=ts,
                source="Log",
                event=msg[:80],
                evidence=f"文件: {lg.get('source_file', 'unknown')}",
            )

        timeline_events = tb.build()

        # 4. 故障域判定
        fault_domains = FaultDomainClassifier.evaluate(
            symptom=symptom,
            recent_release_diff=rel_diff,
            error_logs=logs,
        )

        # 5. 影响范围评估
        impact = ImpactScopeEvaluator.evaluate(
            symptom=symptom,
            fault_domains=fault_domains,
            affected_keywords=[symptom],
        )

        # 6. 历史相似度统计
        similar_stats = self.memory_store.get_similar_incident_stats(search_kw or symptom[:20], days=90)

        # 7. 提取核心证据
        top_domains = [d for d, val in fault_domains.items() if val.get("confidence") in ("High", "Medium")]
        primary_domain = top_domains[0] if top_domains else "Unknown"

        evidence_list = []
        if rel_diff and rel_diff.get("has_changes"):
            mods = [m["module"] for m in rel_diff.get("changed_modules", [])]
            evidence_list.append(f"最新发布 {rel_diff['to_release']} 更新了模块: {', '.join(mods)}")
        if logs:
            evidence_list.append(f"运行日志捕获到 {len(logs)} 条关联报错 (最新: {logs[0].get('message', '')[:60]})")

        return {
            "symptom": symptom,
            "primary_fault_domain": primary_domain,
            "fault_domains": fault_domains,
            "impact_scope": impact,
            "timeline": timeline_events,
            "similar_stats": similar_stats,
            "evidence_list": evidence_list,
            "running_release": running_rel,
            "release_diff": rel_diff,
        }
