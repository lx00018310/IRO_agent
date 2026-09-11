from typing import List, Optional, Tuple, Dict, Any
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    Hypothesis,
    HypothesisStatus,
    HypothesisAction,
    HypothesisUpdate,
)
from iro_agent.investigation.tool_registry import ToolRegistry


class PlannerValidator:
    """
    LLM 排查决策验证器 (Planner Decision Validator)
    负责对 LLM 生成的每一步排查决策进行严格安全审计与契约校验：
    1. 校验工具是否属于只读安全白名单；
    2. 校验参数是否合法、是否含有数据库写或设备控制危险动作；
    3. 校验目标假设 ID 是否属于当前已知假设；
    4. 校验假设生命周期更新建议 (HypothesisUpdate) 的合法性与证据溯源性；
    5. 产生精准错误提示，支持 LLM 自我修正重试。
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()

    def validate(
        self,
        decision: PlannerDecision,
        hypotheses: Optional[List[Hypothesis]] = None,
        evidence_history: Optional[List[Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        全面校验决策合法性
        返回: (is_valid, error_message)
        """
        if not decision:
            return False, "决策对象为空"

        # 0. 假设生命周期更新建议 (HypothesisUpdate) 校验
        valid_ids = [h.hypothesis_id for h in (hypotheses or [])]
        valid_ev_ids = set()
        for e in (evidence_history or []):
            if hasattr(e, "evidence_id") and e.evidence_id:
                valid_ev_ids.add(e.evidence_id)
            elif isinstance(e, dict) and e.get("evidence_id"):
                valid_ev_ids.add(e["evidence_id"])

        for upd in getattr(decision, "hypothesis_updates", []):
            if not isinstance(upd.action, HypothesisAction):
                try:
                    upd.action = HypothesisAction(upd.action)
                except ValueError:
                    return False, f"无效的假设更新动作 '{upd.action}'，允许的动作: {[a.value for a in HypothesisAction]}"

            # 置信度范围校验
            if upd.confidence is not None:
                if not (0.0 <= upd.confidence <= 1.0):
                    return False, f"假设更新置信度 confidence={upd.confidence} 超出合法区间 [0.0, 1.0]"

            # 证据 ID 校验
            if upd.evidence_ids:
                for ev_id in upd.evidence_ids:
                    # 严禁将用户故障描述或随意文本作为 Evidence ID
                    import re
                    if not re.match(r"^[A-Za-z0-9_\-]+$", ev_id) or len(ev_id) > 20:
                        return False, f"非法的 Evidence ID 格式 '{ev_id}'，严禁将用户故障现象或自然语言作为证据引用"
                    if evidence_history is not None and ev_id not in valid_ev_ids:
                        return False, f"假设更新引用了不存在的证据 ID '{ev_id}'。当前有效证据 ID: {list(valid_ev_ids)}"

            # 动作与目标假设关系校验
            if upd.action in (HypothesisAction.SUPPORT, HypothesisAction.CONTRADICT):
                if not upd.hypothesis_id or (valid_ids and upd.hypothesis_id not in valid_ids):
                    return False, f"{upd.action.value} 操作引用的目标假设 ID '{upd.hypothesis_id}' 不存在"
                if not upd.evidence_ids:
                    return False, f"{upd.action.value} 操作必须绑定具体的客观证据 ID (evidence_ids 不能为空)"

            elif upd.action in (HypothesisAction.RETIRE, HypothesisAction.REVISE):
                if not upd.hypothesis_id or (valid_ids and upd.hypothesis_id not in valid_ids):
                    return False, f"{upd.action.value} 操作引用的目标假设 ID '{upd.hypothesis_id}' 不存在"

            elif upd.action == HypothesisAction.ADD:
                if not upd.statement or not upd.statement.strip():
                    return False, "ADD 操作必须提供有效的假设描述 (statement 不能为空)"
                for h in (hypotheses or []):
                    if h.description.strip() == upd.statement.strip():
                        return False, f"ADD 操作描述与已有假设 '{h.hypothesis_id}' 重叠重复"

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
