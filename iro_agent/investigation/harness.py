from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from iro_agent.config import get_config
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.log_reader import LogReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.readers.version_provider import VersionReaderResolver
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.memory.learning_store import LearningMemoryStore
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.knowledge.lookup import ProjectLookupEngine
from iro_agent.analyzer.orchestrator import DiagnosticOrchestrator
from iro_agent.investigation.models import (
    CaseType,
    HypothesisStatus,
    InvestigationStep,
    InvestigationReport,
)
from iro_agent.investigation.classifier import InvestigationCaseClassifier
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner
from iro_agent.investigation.evaluator import EvidenceEvaluator
from iro_agent.investigation.stop_conditions import StopConditions
from iro_agent.investigation.physical_escalation import PhysicalEscalation


class InvestigationHarness:
    """
    现场故障调查套件主控引擎 (Investigation Harness: 假设驱动与动态优先级确定性排查编排器)
    """

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        tool_handlers: Optional[Dict[str, Callable]] = None,
    ):
        self.config = get_config()
        self.audit = audit_logger or AuditLogger()
        self.memory_store = IncidentStore()
        self.learning_store = LearningMemoryStore()
        self.knowledge_store = ProjectKnowledgeStore(
            base_dir=Path(self.config.project_root) if Path(self.config.project_root).exists() else Path.cwd()
        )
        self.lookup_engine = ProjectLookupEngine(store=self.knowledge_store)
        self.orchestrator = DiagnosticOrchestrator(audit_logger=self.audit)

        self.tool_handlers = tool_handlers or self._build_default_tools()

    def _build_default_tools(self) -> Dict[str, Callable]:
        log_reader = LogReader(audit_logger=self.audit)
        db_reader = DatabaseReader(db_config=self.config.database, audit_logger=self.audit)
        v_reader, _ = VersionReaderResolver.resolve(config=self.config, audit_logger=self.audit)

        return {
            "log_search": lambda **kwargs: log_reader.search_logs(**kwargs),
            "db_query": lambda **kwargs: db_reader.execute_query(**kwargs),
            "config_lookup": lambda query, limit=5: self.lookup_engine.config_lookup(query, limit=limit),
            "project_lookup": lambda query: self.lookup_engine.lookup(query),
            "version_current": lambda: v_reader.get_current_version() if v_reader else {"version": "UNKNOWN"},
            "diagnostic_pipeline": lambda symptom: self.orchestrator.run_pipeline(symptom=symptom),
        }

    def investigate(self, symptom: str, verbose: bool = False) -> InvestigationReport:
        """端到端假设驱动现场故障排查流水线"""
        # 1. 前置记忆召回与分类
        recalled_rules = self.learning_store.recall_rules(symptom, project=self.config.project_name, limit=3)
        case_type = InvestigationCaseClassifier.classify(symptom)

        # 2. 生成竞争性假设
        bp = self.knowledge_store.load_blueprint()
        flows = bp.business_flows if bp else []
        hypo_mgr = HypothesisManager(case_type=case_type, symptom=symptom, flows=flows)

        # 3. 制定动态优先级排查步骤序列
        planned_steps = EvidencePlanner.plan_steps(hypo_mgr=hypo_mgr, case_type=case_type, symptom=symptom)
        executed_steps: List[InvestigationStep] = []
        key_evidence: List[str] = []
        stop_reason = ""

        if verbose:
            print("==================================================")
            print("  [Investigation Plan] 调查行动规划")
            print(f"  故障案例定型: {case_type.value}")
            print(f"  初始竞争假设: {len(hypo_mgr.hypotheses)} 个")
            for h in hypo_mgr.hypotheses:
                print(f"    ├─ [{h.hypothesis_id}]: {h.description}")
            print(f"  规划排查步骤: {len(planned_steps)} 步 (按动态优先级执行)")
            print("==================================================")

        # 4. 执行排查与证据评估主循环
        remaining = list(planned_steps)
        while remaining:
            step = remaining.pop(0)

            # 调用只读工具
            handler = self.tool_handlers.get(step.tool)
            tool_output = None
            if handler:
                try:
                    tool_output = handler(**step.tool_args)
                except Exception as e:
                    tool_output = {"error": str(e)}
            else:
                tool_output = {"error": f"Tool {step.tool} not registered"}

            # 评估该证据项
            eval_res = EvidenceEvaluator.evaluate_step(step, tool_output, hypo_mgr)
            executed_steps.append(step)
            key_evidence.append(f"[{step.evidence_tier.name}] {step.reason}: {eval_res.detail}")

            if verbose:
                print(f"[排查步骤 {step.step_id}] -> {step.tool} (优先级: {step.priority})")
                print(f"  ├─ 评估判定: {eval_res.verdict}")
                print(f"  └─ 细节: {eval_res.detail}")

            # 停止条件检查
            should_stop, reason = StopConditions.evaluate(hypo_mgr, executed_steps, remaining)
            if should_stop:
                stop_reason = reason
                if verbose:
                    print(f"\n[终止排查]: {reason}")
                break

        # 5. 结案与物理升级裁决
        top_hypo = hypo_mgr.get_top_hypothesis()
        physical_checklist = []
        primary_cause = None
        confidence = "Medium"

        if top_hypo and top_hypo.status in (HypothesisStatus.CONFIRMED, HypothesisStatus.STRONGLY_SUPPORTED):
            primary_cause = top_hypo.description
            confidence = "High" if top_hypo.status == HypothesisStatus.CONFIRMED else "Medium"
        else:
            # 数字证据不足/耗尽，升级到物理现场检查
            primary_cause = "经多维排查，现有数字事实均无致命异常或已耗尽，高度怀疑现场硬件/物理带外状态异常"
            confidence = "Inconclusive"
            physical_checklist = PhysicalEscalation.generate_checklist(case_type, symptom)

        # 沉淀至 IncidentStore
        try:
            self.memory_store.record_incident({
                "symptom": symptom[:100],
                "fault_domain": case_type.value,
                "severity": "Medium",
                "confidence": confidence,
                "impact_scope": {},
                "related_logs": [e for e in key_evidence if "log" in e.lower()][:5],
                "active_version_provider": "InvestigationHarness",
                "timeline_event_ids": [s.step_id for s in executed_steps],
            })
        except Exception:
            pass

        return InvestigationReport(
            case_type=case_type,
            symptom=symptom,
            hypotheses=hypo_mgr.hypotheses,
            primary_root_cause=primary_cause,
            confidence=confidence,
            key_evidence=key_evidence,
            investigation_trace=executed_steps,
            physical_escalation_checklist=physical_checklist,
            stop_reason=stop_reason,
        )

    def format_human_response(self, report: InvestigationReport) -> str:
        """格式化为极简客观、字数克制的高管现场诊断答复"""
        lines = []
        lines.append(f"**核心结论**：{report.primary_root_cause}。")
        lines.append("")
        lines.append("**关键依据**：")
        if report.key_evidence:
            for ev in report.key_evidence[:3]:
                lines.append(f"- {ev}")
        else:
            lines.append("- 暂无异常数字证据。")

        if report.physical_escalation_checklist:
            lines.append("")
            lines.append("**现场物理排查建议 (Checklist)**：")
            for item in report.physical_escalation_checklist:
                lines.append(f"- {item}")
        elif report.stop_reason:
            lines.append("")
            lines.append(f"**收敛依据**：{report.stop_reason}。")

        return "\n".join(lines)
