import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from iro_agent.config import get_config
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.log_reader import LogReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.readers.web_reader import WebReader
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
    EvidenceRecord,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.trace import InvestigationTrace
from iro_agent.investigation.classifier import InvestigationCaseClassifier
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner
from iro_agent.investigation.evaluator import EvidenceEvaluator
from iro_agent.investigation.stop_conditions import StopConditions, StopReasonCode
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

        web_reader = WebReader(audit_logger=self.audit)

        return {
            "log_search": lambda **kwargs: log_reader.search_logs(**kwargs),
            "db_query": lambda **kwargs: db_reader.execute_query(**kwargs),
            "config_lookup": lambda query, limit=5: self.lookup_engine.config_lookup(query, limit=limit),
            "project_lookup": lambda query: self.lookup_engine.lookup(query),
            "version_current": lambda: v_reader.get_current_version() if v_reader else {"version": "UNKNOWN"},
            "diagnostic_pipeline": lambda symptom: self.orchestrator.run_pipeline(symptom=symptom),
            "web_fetch": lambda **kwargs: web_reader.fetch_page(**kwargs),
        }

    def investigate(self, symptom: str, verbose: bool = False) -> InvestigationReport:
        """端到端假设驱动现场故障排查流水线 (迭代式 Next-Best-Evidence 动态规划闭环)"""
        # 1. 前置记忆召回与分类
        recalled_rules = self.learning_store.recall_rules(symptom, project=self.config.project_name, limit=3)
        case_type = InvestigationCaseClassifier.classify(symptom)

        # 2. 生成竞争性假设
        bp = self.knowledge_store.load_blueprint()
        flows = bp.business_flows if bp else []
        hypo_mgr = HypothesisManager(case_type=case_type, symptom=symptom, flows=flows)

        # 3. 初始化统一排查状态机与全周期轨迹容器
        case_id = f"case_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        state = InvestigationState(
            case_id=case_id,
            symptom=symptom,
            case_type=case_type,
            hypotheses=hypo_mgr.hypotheses,
            max_iterations=10,
            max_tool_calls=12,
        )
        trace = InvestigationTrace(case_id=case_id, symptom=symptom)

        executed_steps: List[InvestigationStep] = []
        key_evidence: List[str] = []
        stop_reason = ""

        if verbose:
            print("==================================================")
            print("  [Investigation Plan] 调查行动规划 (Next-Best-Evidence)")
            print(f"  故障案例定型: {case_type.value}")
            print(f"  初始竞争假设: {len(hypo_mgr.hypotheses)} 个")
            for h in hypo_mgr.hypotheses:
                print(f"    ├─ [{h.hypothesis_id}]: {h.description}")
            print("  排查机制: 逐轮根据最新假设与证据动态规划下一步动作")
            print("==================================================")

        # 4. Next-Best-Evidence 迭代排查与证据评估主循环
        while True:
            # 停止条件检查 (基于 State 与当前假设)
            should_stop, reason, stop_code = StopConditions.evaluate_state(state, hypo_mgr)
            if should_stop:
                stop_reason = reason
                state.stop_reason = reason
                state.final_status = "CONVERGED" if "锁定" in reason or "强支持" in reason else "STOPPED"
                if verbose:
                    print(f"\n[终止排查 ({stop_code})]: {reason}")
                break

            # 动态选取当前信息增益最高且最能区分假设的单步动作
            step = EvidencePlanner.select_next_step(state, hypo_mgr, available_tools=self.tool_handlers)
            if step is None:
                stop_reason = "所有有效数字要素排查步骤均已执行完毕，数字证据耗尽"
                state.stop_reason = stop_reason
                state.final_status = "DIGITAL_EVIDENCE_EXHAUSTED"
                if verbose:
                    print(f"\n[终止排查]: {stop_reason}")
                break

            state.iteration += 1
            hypos_before = [h.model_dump() for h in hypo_mgr.hypotheses]

            # 调用只读工具
            handler = self.tool_handlers.get(step.tool)
            tool_output = None
            is_tool_error = False
            if handler:
                try:
                    tool_output = handler(**step.tool_args)
                except Exception as e:
                    tool_output = {"error": str(e)}
                    is_tool_error = True
            else:
                tool_output = {"error": f"Tool {step.tool} not registered"}
                is_tool_error = True

            if isinstance(tool_output, dict) and tool_output.get("error"):
                is_tool_error = True

            # 记录执行与资源消耗（严格区分正常执行与工具失败）
            state.record_step_execution(step, is_failed=is_tool_error)

            # 评估该证据项并构建结构化 EvidenceRecord
            eval_res = EvidenceEvaluator.evaluate_step(step, tool_output, hypo_mgr)
            ev_record = EvidenceEvaluator.create_evidence_record(step, tool_output, eval_res)
            state.add_evidence(ev_record)

            executed_steps.append(step)
            key_evidence.append(f"[{step.evidence_tier.name}] {step.reason}: {eval_res.detail}")

            hypos_after = [h.model_dump() for h in hypo_mgr.hypotheses]

            # 捕获单轮轨迹
            trace.record_iteration(
                iteration=state.iteration,
                hypotheses_before=hypos_before,
                candidate_steps=[step.model_dump()],
                selected_step=step.model_dump(),
                selection_reason=step.reason,
                tool_call={"tool": step.tool, "args": step.tool_args},
                tool_result_summary=str(eval_res.detail)[:200],
                evidence=ev_record.model_dump(),
                hypotheses_after=hypos_after,
                stop_decision={"should_stop": False, "reason": ""},
            )

            if verbose:
                print(f"[排查步骤 {step.step_id}] -> {step.tool} (优先级: {step.priority})")
                print(f"  ├─ 评估判定: {eval_res.verdict}")
                print(f"  └─ 细节: {eval_res.detail}")

        # 5. 结案与物理升级严格判定
        top_hypo = hypo_mgr.get_top_hypothesis()
        physical_checklist: List[str] = []
        primary_cause = None
        confidence = "Medium"

        if top_hypo and top_hypo.status in (HypothesisStatus.CONFIRMED, HypothesisStatus.STRONGLY_SUPPORTED):
            primary_cause = top_hypo.description
            confidence = "High" if top_hypo.status == HypothesisStatus.CONFIRMED else "Medium"
        else:
            # 严格依据 PhysicalEscalation.should_escalate 判定是否可以升级物理排查
            can_escalate, esc_reason = PhysicalEscalation.should_escalate(state, hypo_mgr)
            if can_escalate:
                primary_cause = "经多维排查，现有数字事实均无致命异常或已耗尽，高度怀疑现场硬件/物理带外状态异常"
                confidence = "Inconclusive"
                physical_checklist = PhysicalEscalation.generate_checklist(case_type, symptom)
                state.physical_escalation_required = True
            else:
                # 存在观测缺口或证据不足，严禁脑补为物理故障！
                primary_cause = f"数字证据不足且存在观测缺口 ({esc_reason})，无法得出确凿物理或软件根因"
                confidence = "Inconclusive"
                state.physical_escalation_required = False

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
            evidence_records=state.evidence,
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
