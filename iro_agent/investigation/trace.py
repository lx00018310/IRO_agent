from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class TraceIteration(BaseModel):
    """单轮排查决策轨迹节点"""
    iteration: int
    hypotheses_before: List[Dict[str, Any]] = Field(default_factory=list)
    candidate_steps: List[Dict[str, Any]] = Field(default_factory=list)
    selected_step: Optional[Dict[str, Any]] = None
    selection_reason: str = ""
    tool_call: Dict[str, Any] = Field(default_factory=dict)
    tool_result_summary: str = ""
    evidence: Optional[Dict[str, Any]] = None
    hypotheses_after: List[Dict[str, Any]] = Field(default_factory=list)
    stop_decision: Dict[str, Any] = Field(default_factory=dict)

    planner_call_mode: Optional[str] = None
    hypothesis_updates_requested: List[Dict[str, Any]] = Field(default_factory=list)
    hypothesis_updates_applied: List[str] = Field(default_factory=list)
    hypothesis_updates_rejected: List[str] = Field(default_factory=list)
    selected_tool: Optional[str] = None
    tool_registered: bool = True
    tool_result_availability: str = "AVAILABLE"
    physical_escalation_requested: bool = False
    physical_escalation_approved: bool = False
    planner_error: Optional[str] = None


class InvestigationTrace(BaseModel):
    """全生命周期排查轨迹捕获器 (Investigation Trace)"""
    case_id: str
    symptom: str
    iterations: List[TraceIteration] = Field(default_factory=list)
    final_decision: Dict[str, Any] = Field(default_factory=dict)

    def record_iteration(
        self,
        iteration: int,
        hypotheses_before: List[Dict[str, Any]],
        candidate_steps: List[Dict[str, Any]],
        selected_step: Optional[Dict[str, Any]],
        selection_reason: str,
        tool_call: Dict[str, Any],
        tool_result_summary: str,
        evidence: Optional[Dict[str, Any]],
        hypotheses_after: List[Dict[str, Any]],
        stop_decision: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """记录一轮完整的决策取证演变"""
        self.iterations.append(
            TraceIteration(
                iteration=iteration,
                hypotheses_before=hypotheses_before,
                candidate_steps=candidate_steps,
                selected_step=selected_step,
                selection_reason=selection_reason,
                tool_call=tool_call,
                tool_result_summary=tool_result_summary,
                evidence=evidence,
                hypotheses_after=hypotheses_after,
                stop_decision=stop_decision,
                **kwargs,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """导出结构化字典"""
        return self.model_dump()
