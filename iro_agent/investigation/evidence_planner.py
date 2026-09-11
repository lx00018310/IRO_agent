from typing import List, Dict, Any
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
