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
    EvidenceTier,
    DecisionAction,
    PlannerDecision,
)
from iro_agent.investigation.state import InvestigationState
from iro_agent.investigation.trace import InvestigationTrace
from iro_agent.investigation.classifier import InvestigationCaseClassifier
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.evidence_planner import EvidencePlanner, DeterministicEvidencePlanner
from iro_agent.investigation.evaluator import EvidenceEvaluator
from iro_agent.investigation.stop_conditions import StopConditions, StopReasonCode
from iro_agent.investigation.physical_escalation import PhysicalEscalation
from iro_agent.investigation.tool_registry import ToolRegistry
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.llm.glm_client import GlmClient


class InvestigationHarness:
    """
    现场故障调查套件主控引擎 (Investigation Harness)
    支持：
    1. 'llm' 模式：基于 LLM 逐轮动态感知与重新规划 (Per-Round Agentic Replanning)；
    2. 'deterministic' 模式：确定性启发式优先级规划 (Deterministic Evidence Planner)。
    """

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        tool_handlers: Optional[Dict[str, Callable]] = None,
        planner_mode: str = "llm",
        llm_planner: Optional[LLMInvestigationPlanner] = None,
        glm_client: Optional[GlmClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        dynamic_hypotheses: bool = True,
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

        # 智能探测 LLM 运行条件：若未提供有效 client 或凭据未配置/格式无效，安全静默降级为确定性模式
        glm_cfg = getattr(self.config, "glm", None)
        api_key = getattr(glm_cfg, "api_key", "") if glm_cfg else ""
        has_valid_llm = bool(
            glm_client
            or llm_planner
            or (api_key and "mock" not in api_key.lower() and "your" not in api_key.lower() and "." in api_key)
        )
        if planner_mode == "llm" and not has_valid_llm:
            self.planner_mode = "deterministic"
        else:
            self.planner_mode = planner_mode

        self.tool_handlers = tool_handlers or self._build_default_tools()
        self.tool_registry = tool_registry or ToolRegistry(include_legacy_pipelines=(self.planner_mode == "deterministic"))

        if self.planner_mode == "llm":
            self.dynamic_hypotheses = True
            if glm_client:
                self.glm_client = glm_client
            elif llm_planner and getattr(llm_planner, "glm_client", None):
                self.glm_client = llm_planner.glm_client
            else:
                self.glm_client = GlmClient(audit_logger=self.audit)

            self.llm_planner = llm_planner or LLMInvestigationPlanner(
                glm_client=self.glm_client,
                registry=self.tool_registry,
            )
        else:
            self.dynamic_hypotheses = dynamic_hypotheses
            self.glm_client = glm_client
            self.llm_planner = None

    def _build_default_tools(self) -> Dict[str, Callable]:
        log_reader = LogReader(audit_logger=self.audit)
        db_reader = DatabaseReader(db_config=self.config.database, audit_logger=self.audit)
        v_reader, _ = VersionReaderResolver.resolve(config=self.config, audit_logger=self.audit)
        web_reader = WebReader(audit_logger=self.audit)

        tools: Dict[str, Callable] = {
            "log_search": lambda **kwargs: log_reader.search_logs(**kwargs),
            "db_query": lambda **kwargs: db_reader.execute_query(**kwargs),
            "config_lookup": lambda query, limit=5: self.lookup_engine.config_lookup(query, limit=limit),
            "project_lookup": lambda query: self.lookup_engine.lookup(query),
            "version_current": lambda: v_reader.get_current_version() if v_reader else {"version": "UNKNOWN"},
            "web_fetch": lambda **kwargs: web_reader.fetch_page(**kwargs),
            "plc_read": lambda **kwargs: {
                "status": "UNAVAILABLE",
                "error": "PLC reader adapter is not configured in current environment: observability_gap",
            },
            "robot_query": lambda **kwargs: {
                "status": "UNAVAILABLE",
                "error": "Robot query adapter is not configured in current environment: observability_gap",
            },
        }
        if getattr(self, "planner_mode", None) == "deterministic":
            tools["diagnostic_pipeline"] = lambda symptom: self.orchestrator.run_pipeline(symptom=symptom)
        return tools

    def investigate(self, symptom: str, verbose: bool = False) -> InvestigationReport:
        """端到端假设驱动现场故障排查流水线 (迭代式 Next-Best-Evidence 逐轮重规划智能闭环)"""
        # 1. 前置记忆召回与分类
        recalled_rules = self.learning_store.recall_rules(symptom, project=self.config.project_name, limit=3)
        case_type = InvestigationCaseClassifier.classify(symptom)

        # 2. 生成竞争性假设 (支持 LLM 动态推导或确定性模板降级)
        bp = self.knowledge_store.load_blueprint()
        flows = bp.business_flows if bp else []
        hypo_mgr = HypothesisManager(
            case_type=case_type,
            symptom=symptom,
            flows=flows,
            glm_client=self.glm_client if (self.planner_mode == "llm" and self.dynamic_hypotheses) else None,
        )

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
            print(f"  [Investigation Plan] 调查行动规划 (模式: {self.planner_mode.upper()})")
            print(f"  故障案例定型: {case_type.value}")
            print(f"  初始竞争假设: {len(hypo_mgr.hypotheses)} 个")
            for h in hypo_mgr.hypotheses:
                print(f"    ├─ [{h.hypothesis_id}]: {h.description}")
            print("  排查机制: 逐轮根据最新假设与证据动态规划下一步动作")
            print("==================================================")

        # 4. Next-Best-Evidence 逐轮重规划迭代排查主循环
        while True:
            # 基础停止条件检查 (状态与假设确证)
            should_stop, reason, stop_code = StopConditions.evaluate_state(state, hypo_mgr)
            if should_stop:
                stop_reason = reason
                state.stop_reason = reason
                state.final_status = "CONVERGED" if "锁定" in reason or "强支持" in reason else "STOPPED"
                if verbose:
                    print(f"\n[终止排查 ({stop_code})]: {reason}")
                break

            step: Optional[InvestigationStep] = None

            # 分支 A: LLM 逐轮动态规划
            if self.planner_mode == "llm" and self.llm_planner:
                remaining_budget = state.max_iterations - state.iteration
                if remaining_budget <= 0 or len(state.executed_steps) >= state.max_tool_calls:
                    stop_reason = "达到最大调查步数或调用配额上限"
                    state.stop_reason = stop_reason
                    state.final_status = "BUDGET_EXHAUSTED"
                    break

                decision = self.llm_planner.plan_next_step(
                    symptom=symptom,
                    hypotheses=hypo_mgr.hypotheses,
                    evidence_history=state.evidence,
                    remaining_budget=remaining_budget,
                )

                # 应用大模型规划器对假设提出的生命周期更新
                if getattr(decision, "hypothesis_updates", None):
                    applied = hypo_mgr.apply_updates(decision.hypothesis_updates, evidence_history=state.evidence)
                    for upd in decision.hypothesis_updates:
                        if upd.hypothesis_id:
                            for ev_id in upd.evidence_ids:
                                for ev in state.evidence:
                                    if ev.evidence_id == ev_id:
                                        if upd.action in (HypothesisAction.SUPPORT, HypothesisAction.REVISE):
                                            if upd.hypothesis_id not in ev.supports:
                                                ev.supports.append(upd.hypothesis_id)
                                        elif upd.action in (HypothesisAction.CONTRADICT, HypothesisAction.RETIRE):
                                            if upd.hypothesis_id not in ev.contradicts:
                                                ev.contradicts.append(upd.hypothesis_id)
                    if verbose and applied:
                        print(f"  [假设生命周期动态更新]: {', '.join(applied)}")

                if decision.error and "PLANNER_ERROR" in decision.error:
                    stop_reason = f"PLANNER_ERROR: {decision.error}"
                    state.stop_reason = stop_reason
                    state.final_status = "PLANNER_ERROR"
                    if verbose:
                        print(f"\n[规划器严重异常终止]: {stop_reason}")
                    break
                elif decision.decision == DecisionAction.CONVERGE:
                    stop_reason = decision.reason or decision.thought or "LLM 规划器根据当前证据判定收敛结案"
                    state.stop_reason = stop_reason
                    state.final_status = "CONVERGED"
                    if verbose:
                        print(f"\n[LLM 主动收敛]: {stop_reason}")
                    break

                elif decision.decision == DecisionAction.ESCALATE_PHYSICAL:
                    can_escalate, guardrail_reason = PhysicalEscalation.should_escalate(state, hypo_mgr)
                    if can_escalate:
                        stop_reason = decision.reason or decision.thought or "数字事实排查未见异常，Harness 批准升级现场物理排查"
                        state.stop_reason = stop_reason
                        state.physical_escalation_required = True
                        state.final_status = "PHYSICAL_ESCALATION"
                        if verbose:
                            print(f"\n[Harness 批准物理升级]: {stop_reason}")
                        break
                    else:
                        if verbose:
                            print(f"\n[Harness 拦截未合规物理升级]: {guardrail_reason}")
                        state.unknown_factors.append(f"物理升级请求被安全防护拦截: {guardrail_reason}")
                        stop_reason = f"物理升级未通过安全防护 ({guardrail_reason})，数字取证未收敛且无法升级"
                        state.stop_reason = stop_reason
                        state.final_status = "INSUFFICIENT_EVIDENCE"
                        state.physical_escalation_required = False
                        break

                elif decision.decision == DecisionAction.GIVE_UP:
                    stop_reason = decision.reason or decision.thought or "LLM 判定无可继续排查路径，放弃排查"
                    state.stop_reason = stop_reason
                    state.final_status = "STOPPED"
                    if verbose:
                        print(f"\n[LLM 终止排查]: {stop_reason}")
                    break

                elif decision.decision == DecisionAction.EXECUTE_TOOL:
                    tool_name = decision.tool_name or "log_search"
                    spec = self.tool_registry.get_tool(tool_name)
                    tier = spec.tier if spec else EvidenceTier.TIER_1A_RUNTIME_DIGITAL
                    step = InvestigationStep(
                        step_id=f"step_{state.iteration + 1}",
                        hypothesis_ids=[decision.target_hypothesis] if decision.target_hypothesis else [],
                        evidence_tier=tier,
                        evidence_type=tool_name,
                        tool=tool_name,
                        tool_args=decision.tool_arguments or {},
                        reason=decision.reason or decision.thought or f"执行 {tool_name} 采集证据",
                        priority=50,
                    )

            # 分支 B: 确定性启发式优先级规划 (Deterministic Mode)
            else:
                step = EvidencePlanner.select_next_step(state, hypo_mgr, available_tools=self.tool_handlers)
                if step is None:
                    stop_reason = "所有有效数字要素排查步骤均已执行完毕，数字证据耗尽"
                    state.stop_reason = stop_reason
                    state.final_status = "DIGITAL_EVIDENCE_EXHAUSTED"
                    if verbose:
                        print(f"\n[终止排查]: {stop_reason}")
                    break

            if not step:
                break

            state.iteration += 1
            hypos_before = [h.model_dump() for h in hypo_mgr.hypotheses]

            # 执行只读工具
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

            # 记录执行与资源消耗
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
                planner_call_mode="pure_structured_llm" if self.planner_mode == "llm" else "deterministic",
                hypothesis_updates_requested=[u.model_dump() for u in getattr(decision, "hypothesis_updates", [])] if (self.planner_mode == "llm" and getattr(decision, "hypothesis_updates", None)) else [],
                hypothesis_updates_applied=applied if (self.planner_mode == "llm" and 'applied' in locals() and applied) else [],
                selected_tool=step.tool,
                tool_registered=step.tool in self.tool_handlers,
                tool_result_availability="OBSERVABILITY_GAP" if ev_record.error_type == "OBSERVABILITY_GAP" else "AVAILABLE",
                physical_escalation_requested=(self.planner_mode == "llm" and getattr(decision, "decision", None) == DecisionAction.ESCALATE_PHYSICAL),
                physical_escalation_approved=(state.final_status == "PHYSICAL_ESCALATION"),
                planner_error=getattr(decision, "error", None) if self.planner_mode == "llm" else None,
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
        elif state.final_status == "PLANNER_ERROR":
            primary_cause = f"排查规划异常: {stop_reason}"
            confidence = "Low"
            state.physical_escalation_required = False
        elif state.final_status == "INSUFFICIENT_EVIDENCE":
            primary_cause = f"数字证据不足且未收敛 ({stop_reason})"
            confidence = "Inconclusive"
            state.physical_escalation_required = False
        else:
            can_escalate, esc_reason = PhysicalEscalation.should_escalate(state, hypo_mgr)
            if can_escalate:
                primary_cause = "经多维排查，现有数字事实均无致命异常或已耗尽，高度怀疑现场硬件/物理带外状态异常"
                confidence = "High"
                physical_checklist = PhysicalEscalation.generate_checklist(case_type, symptom)
                state.physical_escalation_required = True
                state.final_status = "PHYSICAL_ESCALATION"
            else:
                primary_cause = f"数字证据不足且存在观测缺口 ({esc_reason})，无法得出确凿物理或软件根因"
                confidence = "Inconclusive"
                state.physical_escalation_required = False

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
            final_status=state.final_status,
            key_evidence=key_evidence,
            investigation_trace=executed_steps,
            physical_escalation_checklist=physical_checklist,
            physical_escalation_required=state.physical_escalation_required,
            stop_reason=stop_reason,
            unknown_factors=state.unknown_factors,
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
