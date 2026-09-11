from typing import List, Dict, Any, Optional
from iro_agent.investigation.models import CaseType, EvidenceTier, InvestigationStep
from iro_agent.investigation.hypotheses import HypothesisManager
from iro_agent.investigation.priorities import PriorityCalculator


class EvidencePlanner:
    """证据排查行动规划器 (Evidence Planner)"""

    @classmethod
    def plan_steps(
        cls,
        hypo_mgr: HypothesisManager,
        case_type: CaseType,
        symptom: str,
    ) -> List[InvestigationStep]:
        steps: List[InvestigationStep] = []
        step_counter = 1

        # 1. 针对 PLC 故障的排查规划
        if case_type == CaseType.PLC_SIGNAL_ERROR:
            p_plc_log = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_2_SYSTEM_BOUNDARY, case_type, evidence_tag="plc_log", cost=5, info_gain=30
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H2", "H3"],
                    evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                    evidence_type="plc_communication_log",
                    tool="log_search",
                    tool_args={"keyword": "PLC", "max_results": 10},
                    reason="检索后端与PLC的通信报文与重连/超时记录",
                    priority=p_plc_log,
                )
            )
            step_counter += 1

            p_db = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="db_state", cost=10, info_gain=25
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H3"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="dock_task_status",
                    tool="db_query",
                    tool_args={"query": "SELECT * FROM dock_task ORDER BY id DESC LIMIT 5"},
                    reason="核实当前月台任务状态与前置工序条件",
                    priority=p_db,
                )
            )
            step_counter += 1

        # 2. 针对机器人执行异常的排查规划
        elif case_type == CaseType.ROBOT_EXECUTION_ERROR:
            p_robot_log = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_2_SYSTEM_BOUNDARY, case_type, evidence_tag="robot_api", cost=5, info_gain=35
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H3", "H4"],
                    evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                    evidence_type="robot_dispatch_log",
                    tool="log_search",
                    tool_args={"keyword": "robot", "max_results": 10},
                    reason="排查向机器人发送动作指令及返回回执的日志",
                    priority=p_robot_log,
                )
            )
            step_counter += 1

            p_db_task = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="db_task", cost=10, info_gain=30
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H2"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="task_creation_state",
                    tool="db_query",
                    tool_args={"query": "SELECT * FROM dock_task ORDER BY id DESC LIMIT 5"},
                    reason="确认调度主任务是否已在数据库中成功生成",
                    priority=p_db_task,
                )
            )
            step_counter += 1

        # 3. 针对配置错误的排查规划
        elif case_type == CaseType.CONFIGURATION_ERROR:
            p_cfg = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="config_lookup", cost=5, info_gain=35
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H1", "H2"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="effective_configuration",
                    tool="config_lookup",
                    tool_args={"query": symptom},
                    reason="查阅 ConfigCatalog 获取现场实际生效配置项与层级覆盖来源",
                    priority=p_cfg,
                )
            )
            step_counter += 1

        # 4. 针对版本或应用报错排查规划
        elif case_type in (CaseType.APPLICATION_ERROR, CaseType.VERSION_CHANGE_ERROR):
            p_err_log = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="error_log", cost=5, info_gain=35
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H1"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="application_error_logs",
                    tool="log_search",
                    tool_args={"level": "ERROR", "max_results": 10},
                    reason="检索工控机应用运行时的最近核心报错与异常调用堆栈",
                    priority=p_err_log,
                )
            )
            step_counter += 1

            p_ver = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="version_status", cost=5, info_gain=25
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H1"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="current_version_info",
                    tool="version_current",
                    tool_args={},
                    reason="获取当前工控机运行软件的确定版本与发版时间",
                    priority=p_ver,
                )
            )
            step_counter += 1

        # 默认通用排查步骤
        else:
            p_general_log = PriorityCalculator.calculate_priority(
                EvidenceTier.TIER_1A_RUNTIME_DIGITAL, case_type, evidence_tag="log", cost=5, info_gain=30
            )
            steps.append(
                InvestigationStep(
                    step_id=f"step_{step_counter}",
                    hypothesis_ids=["H1"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="system_logs",
                    tool="log_search",
                    tool_args={"keyword": symptom.split()[0] if symptom else None, "max_results": 10},
                    reason="根据故障现象关键词检索系统运行日志",
                    priority=p_general_log,
                )
            )
            step_counter += 1

        # 按优先级降序排序
        steps.sort(key=lambda s: s.priority, reverse=True)
        return steps

    @classmethod
    def select_next_step(
        cls,
        state: Any,
        hypo_mgr: Any,
        available_tools: Optional[Any] = None,
    ) -> Optional[InvestigationStep]:
        """
        Next-Best-Evidence 动态决策：
        根据当前活跃竞争假设、已有客观证据与历史步骤，动态构建候选动作池，
        结合假设区分增益、可观测性与重复惩罚计算分值，选出单步最优排查动作。
        """
        if getattr(state, "is_budget_exhausted", lambda: False)():
            return None

        candidates: List[InvestigationStep] = []
        case_type = getattr(state, "case_type", CaseType.APPLICATION_ERROR)
        symptom = getattr(state, "symptom", "")

        # 1. 基础候选池（根据案例特征构建）
        if case_type == CaseType.PLC_SIGNAL_ERROR:
            candidates.append(
                InvestigationStep(
                    step_id="cand_plc_log",
                    hypothesis_ids=["H2", "H3"],
                    evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                    evidence_type="plc_communication_log",
                    tool="log_search",
                    tool_args={"keyword": "PLC", "max_results": 10},
                    reason="检索后端与PLC的通信报文与超时/重连记录",
                )
            )
            candidates.append(
                InvestigationStep(
                    step_id="cand_db_task",
                    hypothesis_ids=["H3"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="dock_task_status",
                    tool="db_query",
                    tool_args={"query": "SELECT * FROM dock_task ORDER BY id DESC LIMIT 5"},
                    reason="核实当前任务状态与前置工序数据库记录",
                )
            )
        elif case_type == CaseType.ROBOT_EXECUTION_ERROR:
            candidates.append(
                InvestigationStep(
                    step_id="cand_robot_log",
                    hypothesis_ids=["H3", "H4"],
                    evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                    evidence_type="robot_dispatch_log",
                    tool="log_search",
                    tool_args={"keyword": "robot", "max_results": 10},
                    reason="排查向机器人发送动作指令及返回回执的通信日志",
                )
            )
            candidates.append(
                InvestigationStep(
                    step_id="cand_db_task",
                    hypothesis_ids=["H2"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="task_creation_state",
                    tool="db_query",
                    tool_args={"query": "SELECT * FROM dock_task ORDER BY id DESC LIMIT 5"},
                    reason="确认调度任务是否已在数据库中成功生成",
                )
            )
        elif case_type == CaseType.CONFIGURATION_ERROR:
            candidates.append(
                InvestigationStep(
                    step_id="cand_cfg",
                    hypothesis_ids=["H1", "H2"],
                    evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                    evidence_type="effective_configuration",
                    tool="config_lookup",
                    tool_args={"query": symptom},
                    reason="查阅 ConfigCatalog 获取现场实际生效配置项",
                )
            )

        # 通用候选：核心报错日志检索
        candidates.append(
            InvestigationStep(
                step_id="cand_app_err",
                hypothesis_ids=["H1"],
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="application_error_logs",
                tool="log_search",
                tool_args={"level": "ERROR", "max_results": 10},
                reason="检索工控机应用运行时的最近核心报错与堆栈",
            )
        )

        # 通用候选：当前运行版本核查
        candidates.append(
            InvestigationStep(
                step_id="cand_version",
                hypothesis_ids=["H1"],
                evidence_tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
                evidence_type="current_version_info",
                tool="version_current",
                tool_args={},
                reason="获取工控机当前生效运行软件版本",
            )
        )

        # 2. 根据新近证据动态衍生自适应动作 (Replan by Evidence)
        for ev in getattr(state, "evidence", []):
            raw = (getattr(ev, "raw_summary", "") or "").upper()
            if "WAIT_P2C" in raw or "P2C" in raw:
                candidates.append(
                    InvestigationStep(
                        step_id="cand_p2c_signal",
                        hypothesis_ids=["H2", "H3"],
                        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                        evidence_type="p2c_signal_boundary",
                        tool="log_search",
                        tool_args={"keyword": "P2C", "max_results": 10},
                        reason="深入检索 P2C 信号接收与边界交互细节",
                    )
                )
            if "TIMEOUT" in raw or "HEARTBEAT" in raw:
                candidates.append(
                    InvestigationStep(
                        step_id="cand_heartbeat",
                        hypothesis_ids=["H3", "H4"],
                        evidence_tier=EvidenceTier.TIER_2_SYSTEM_BOUNDARY,
                        evidence_type="heartbeat_trace",
                        tool="log_search",
                        tool_args={"keyword": "heartbeat", "max_results": 10},
                        reason="排查通信心跳状态与断连轨迹",
                    )
                )

        # 3. 过滤工具不可用项
        if available_tools is not None:
            tool_keys = available_tools.keys() if hasattr(available_tools, "keys") else available_tools
            candidates = [c for c in candidates if c.tool in tool_keys]

        # 4. 动态打分并选优
        scored: List[tuple] = []
        for cand in candidates:
            score = PriorityCalculator.score_candidate_step(cand, state, hypo_mgr)
            if score > 0:
                cand.priority = int(score)
                scored.append((score, cand))

        if not scored:
            return None

        # 排序：优先按动态 Score，同分优先看已配置 priority
        scored.sort(key=lambda x: (x[0], x[1].priority), reverse=True)
        best_score, best_cand = scored[0]

        executed_len = len(getattr(state, "executed_steps", [])) + len(getattr(state, "failed_steps", []))
        best_cand.step_id = f"step_{executed_len + 1}"
        return best_cand

