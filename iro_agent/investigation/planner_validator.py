from typing import List, Optional, Tuple, Dict, Any
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    Hypothesis,
    HypothesisStatus,
)
from iro_agent.investigation.tool_registry import ToolRegistry


class PlannerValidator:
    """
    LLM 排查决策验证器 (Planner Decision Validator)
    负责对 LLM 生成的每一步排查决策进行严格安全审计与契约校验：
    1. 校验工具是否属于只读安全白名单；
    2. 校验参数是否合法、是否含有数据库写或设备控制危险动作；
    3. 校验目标假设 ID 是否属于当前已知假设；
    4. 产生精准错误提示，支持 LLM 自我修正重试。
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()

    def validate(
        self,
        decision: PlannerDecision,
        hypotheses: Optional[List[Hypothesis]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        全面校验决策合法性
        返回: (is_valid, error_message)
        """
        if not decision:
            return False, "决策对象为空"

        # 1. 动作类型校验
        if not isinstance(decision.decision, DecisionAction):
            try:
                decision.decision = DecisionAction(decision.decision)
            except ValueError:
                return False, f"无效的决策动作类型 '{decision.decision}'，允许的动作: {[a.value for a in DecisionAction]}"

        action = decision.decision

        # 2. 如果是收敛、物理升级或放弃，不需要工具执行，直接通过
        if action in (DecisionAction.CONVERGE, DecisionAction.ESCALATE_PHYSICAL, DecisionAction.GIVE_UP):
            return True, None

        # 3. 如果是工具执行 (EXECUTE_TOOL)
        if action == DecisionAction.EXECUTE_TOOL:
            if not decision.tool_name:
                return False, "动作 EXECUTE_TOOL 必须指定 'tool_name'"

            # 只读白名单与参数深度校验
            valid_tool, tool_err = self.registry.validate_call(
                tool_name=decision.tool_name,
                arguments=decision.tool_arguments or {},
            )
            if not valid_tool:
                return False, tool_err

            # 4. 目标假设关联性校验
            valid_ids = [h.hypothesis_id for h in (hypotheses or [])]
            if valid_ids:
                if decision.target_hypothesis:
                    if decision.target_hypothesis not in valid_ids:
                        return False, f"指定的 target_hypothesis '{decision.target_hypothesis}' 不存在。当前可用假设 ID: {valid_ids}"
                else:
                    # 如果未显式提供 target_hypothesis，尝试自动关联当前未决的首个假设
                    unresolved = [h.hypothesis_id for h in (hypotheses or []) if h.status == HypothesisStatus.UNRESOLVED]
                    if unresolved:
                        decision.target_hypothesis = unresolved[0]
                    else:
                        decision.target_hypothesis = valid_ids[0]

        return True, None
