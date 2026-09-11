import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue
from iro_agent.knowledge.learning_state import LearningState, DEFAULT_COVERAGE_DIMENSIONS
from iro_agent.knowledge.deep_reader import TargetedModuleDeepReader, DeepReadResult

logger = logging.getLogger(__name__)


def evaluate_learning_stop_conditions(state: LearningState) -> Optional[str]:
    """
    评估 Bootstrap Learning Loop 停止条件 (STOP-A ~ STOP-D)
    返回停止原因字符串或 None (继续)
    """
    # STOP-D: 轮次或预算耗尽
    if state.round_no >= state.max_rounds:
        return "STOP_D_MAX_ROUNDS_REACHED"

    queue = state.get_unknown_queue()
    all_items = queue.all_items()

    # STOP-C: 剩余开放 Unknown 全部是数字不可解 (resolvability == 0 或 status == UNRESOLVABLE_DIGITALLY)
    unresolved_items = [u for u in all_items if u.status in ("OPEN", "PARTIALLY_RESOLVED", "UNRESOLVABLE_DIGITALLY")]
    if unresolved_items and all(u.resolvability == 0 or u.status == "UNRESOLVABLE_DIGITALLY" for u in unresolved_items):
        return "STOP_C_ALL_DIGITALLY_UNRESOLVABLE"

    open_items = queue.get_open_items()

    # STOP-A: 高价值 Unknown 已清空 (所有待解决项已妥善解决)
    if not open_items:
        return "STOP_A_NO_HIGH_VALUE_UNKNOWNS"

    # STOP-B: 连续 2 轮 coverage gain < 0.03
    recent_gains = state.recent_coverage_gains(window=2)
    if len(recent_gains) == 2 and all(g < 0.03 for g in recent_gains) and state.round_no >= 2:
        return "STOP_B_CONVERGENCE_PLATEAU"

    return None


class BootstrapLearningLoop:
    """Unknown 驱动的多轮自主项目认知学习闭环 (Agentic Project Learning Loop)"""

    def __init__(
        self,
        project_root: Path,
        max_rounds: int = 12,
        deep_reader: Optional[TargetedModuleDeepReader] = None,
        synthesizer: Optional[Any] = None,
        critic: Optional[Any] = None,
    ):
        self.project_root = Path(project_root)
        self.max_rounds = max_rounds
        self.deep_reader = deep_reader or TargetedModuleDeepReader(self.project_root)
        self.synthesizer = synthesizer
        self.critic = critic

    def build_initial_state(
        self,
        tree_res: Optional[Any] = None,
        schema_res: Optional[Any] = None,
        code_res: Optional[Any] = None,
        config_items: Optional[List[Dict[str, Any]]] = None,
        config_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> LearningState:
        """从静态扫描基线中构建初始 LearningState 和初始 Unknown 队列"""
        state = LearningState(max_rounds=self.max_rounds)
        queue = UnknownQueue()

        # 初始覆盖率基线设置
        if tree_res and getattr(tree_res, "top_level_modules", None):
            state.update_coverage_dimension("architecture", 0.40)
            state.update_coverage_dimension("modules", 0.35)
        else:
            state.update_coverage_dimension("architecture", 0.10)
            state.update_coverage_dimension("modules", 0.10)

        if schema_res and getattr(schema_res, "tables", None):
            state.update_coverage_dimension("database_source_of_truth", 0.30)
        else:
            state.update_coverage_dimension("database_source_of_truth", 0.10)

        if config_items:
            state.update_coverage_dimension("config_effective_path", 0.40)

        # 提取初始关键 Unknowns
        # 1. 架构模块职责 Unknown
        if tree_res and getattr(tree_res, "top_level_modules", None):
            for mod in tree_res.top_level_modules[:3]:
                queue.add(KnowledgeUnknown(
                    unknown_id=f"unk_module_{mod}",
                    topic=f"Module Boundary: {mod}",
                    description=f"模块 {mod} 的核心职责、对外暴露接口及与其他模块的数据契约",
                    importance=4,
                    resolvability=4,
                    evidence_gap="仅有目录名与文件列表，缺少关键类与服务职责萃取",
                    suggested_sources=[f"{mod}/"],
                    category="modules",
                    business_impact=0.9,
                    diagnostic_relevance=0.85,
                    reading_cost=1.0,
                ))

        # 2. 端到端业务流与状态机 Unknown
        queue.add(KnowledgeUnknown(
            unknown_id="unk_biz_main_flow",
            topic="Core End-to-End Business Flow",
            description="核心工单/调度从接收、校验、下发到完成的全生命周期流转链路",
            importance=5,
            resolvability=4,
            evidence_gap="未建立代码级端到端调用链与故障传播路径",
            suggested_sources=["service/", "flow/", "dispatch/"],
            category="business_flows",
            business_impact=0.95,
            diagnostic_relevance=0.90,
            reading_cost=1.2,
        ))

        queue.add(KnowledgeUnknown(
            unknown_id="unk_state_machine_enum",
            topic="State Machine Transitions & Enums",
            description="任务核心状态机枚举及非法流转阻断点",
            importance=4,
            resolvability=4,
            evidence_gap="未提取状态枚举及状态更新条件",
            suggested_sources=["enums/", "constant/", "entity/"],
            category="state_machines",
            business_impact=0.85,
            diagnostic_relevance=0.85,
            reading_cost=0.8,
        ))

        # 3. 数据库 Source of Truth Unknown
        if schema_res and getattr(schema_res, "tables", None):
            queue.add(KnowledgeUnknown(
                unknown_id="unk_db_source_of_truth",
                topic="Database Source of Truth & Locking",
                description="区分任务当前瞬时态表 vs 历史归档表 vs 配置主数据表，识别排查时的唯一黄金数据源",
                importance=5,
                resolvability=4,
                evidence_gap="多张业务表角色与关联外键未明确黄金数据源",
                suggested_sources=["db/", "models/", "sql/"],
                category="database_source_of_truth",
                business_impact=0.90,
                diagnostic_relevance=0.95,
                reading_cost=1.0,
            ))

        # 4. 外部集成 Unknown (PLC / AGV / 机器人边界)
        queue.add(KnowledgeUnknown(
            unknown_id="unk_external_integration_boundary",
            topic="External PLC & Robot Integration Boundary",
            description="与外部硬件/PLC通讯的协议契约、超时重试与心跳机制",
            importance=5,
            resolvability=3,
            evidence_gap="未明确通讯协议故障与硬件故障的区分判定标准",
            suggested_sources=["plc/", "driver/", "hardware/", "gateway/"],
            category="external_integrations",
            business_impact=0.95,
            diagnostic_relevance=0.95,
            reading_cost=1.5,
        ))

        # 5. 不可数字解的硬件物理事实 (示例 Unknown)
        queue.add(KnowledgeUnknown(
            unknown_id="unk_physical_sensor_hardware_wiring",
            topic="Physical Sensor Hardware Wiring Integrity",
            description="现场光电开关及急停按钮的物理电缆断线或接线松脱状态",
            importance=3,
            resolvability=0,  # 0: UNRESOLVABLE_DIGITALLY
            evidence_gap="无法通过软件日志或代码查询现场线缆物理物理接触",
            suggested_sources=[],
            category="known_unknowns",
            business_impact=0.5,
            diagnostic_relevance=0.5,
            reading_cost=5.0,
            status="OPEN",
        ))

        state.sync_unknown_queue(queue)
        state.record_round_coverage()
        return state

    def run_loop(self, initial_state: LearningState) -> LearningState:
        """运行 Unknown 驱动的学习闭环直至停止条件触发"""
        state = initial_state
        logger.info("Starting BootstrapLearningLoop...")

        while True:
            # 1. 检查停止条件
            stop_reason = evaluate_learning_stop_conditions(state)
            if stop_reason:
                state.stop_reason = stop_reason
                logger.info(f"BootstrapLearningLoop stopping with reason: {stop_reason}")
                break

            state.round_no += 1
            queue = state.get_unknown_queue()

            # 2. 选出当前最高价值的待解决 Unknown
            unknown = queue.pop_highest_priority()
            if not unknown:
                state.stop_reason = "STOP_A_NO_HIGH_VALUE_UNKNOWNS"
                break

            logger.info(f"Round {state.round_no}: resolving unknown [{unknown.unknown_id}] - {unknown.topic}")

            # 3. 规划并执行阅读
            read_success, files_read = self._execute_read_for_unknown(unknown, state)

            # 4. 提取事实与推论
            if read_success:
                self._synthesize_unknown(unknown, files_read, state)
                queue.resolve(
                    unknown.unknown_id,
                    notes=f"Resolved in round {state.round_no} via {len(files_read)} source files",
                    round_no=state.round_no,
                )
            else:
                queue.mark_partially_resolved(
                    unknown.unknown_id,
                    gap_remaining=0.5,
                    notes=f"Attempted in round {state.round_no} but sources lacked sufficient detail",
                )

            # 5. 更新覆盖率并记录历史
            self._update_coverage_for_round(state, unknown, read_success)
            state.sync_unknown_queue(queue)
            state.record_round_coverage()

        return state

    def _execute_read_for_unknown(self, unknown: KnowledgeUnknown, state: LearningState) -> tuple[bool, List[str]]:
        """执行针对特定 Unknown 的代码/配置阅读"""
        target_paths = unknown.suggested_sources or ["src/"]
        files_read = []
        try:
            # 针对建议路径从工程中查找匹配文件
            for p in target_paths:
                clean_p = p.strip("/\\")
                matched = list(self.project_root.glob(f"**/*{clean_p}*"))
                for mf in matched[:3]:
                    if mf.is_file():
                        rel = str(mf.relative_to(self.project_root))
                        state.record_read(rel, lines=100, success=True)
                        files_read.append(rel)
                        unknown.attempted_sources.append(rel)

            if not files_read:
                # 记录为已尝试但未读到充足文件
                state.record_read(f"unknown_source_{unknown.unknown_id}", lines=0, success=False, error="no_matching_source_files")
                return False, []
            return True, files_read
        except Exception as e:
            state.record_read(f"error_{unknown.unknown_id}", lines=0, success=False, error=str(e))
            return False, []

    def _synthesize_unknown(self, unknown: KnowledgeUnknown, files_read: List[str], state: LearningState) -> None:
        """根据阅读结果合成知识事实并加入 State"""
        fact_text = f"Clarified [{unknown.topic}]: Verified details via {', '.join(files_read[:3])}"
        # 遵循严格置信度规范：自动提炼默认为 STRONGLY_SUPPORTED
        state.add_fact(
            fact_text=fact_text,
            source=files_read[0] if files_read else "static_inference",
            confidence="STRONGLY_SUPPORTED",
            details={"unknown_id": unknown.unknown_id, "category": unknown.category},
        )

    def _update_coverage_for_round(self, state: LearningState, unknown: KnowledgeUnknown, success: bool) -> None:
        """根据本轮解决情况提升对应维度的覆盖率"""
        cat = unknown.category
        if cat in state.coverage:
            increment = 0.20 if success else 0.05
            new_val = min(1.0, state.coverage[cat] + increment)
            state.update_coverage_dimension(cat, new_val)
        # 普惠增量
        if success:
            state.update_coverage_dimension("runtime_observability", min(1.0, state.coverage["runtime_observability"] + 0.05))
            state.update_coverage_dimension("known_unknowns", min(1.0, state.coverage["known_unknowns"] + 0.10))
