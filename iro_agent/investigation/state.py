from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from iro_agent.investigation.models import (
    CaseType,
    Hypothesis,
    InvestigationStep,
    EvidenceRecord,
)


class InvestigationState(BaseModel):
    """
    统一排查运行状态机 (Investigation State)
    跟踪调查全生命周期中假设演进、证据收集、步骤执行、资源消耗与停止决策。
    """
    case_id: str
    symptom: str
    case_type: CaseType

    hypotheses: List[Hypothesis] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    executed_steps: List[InvestigationStep] = Field(default_factory=list)
    failed_steps: List[InvestigationStep] = Field(default_factory=list)

    iteration: int = 0
    max_iterations: int = 10

    tool_calls: int = 0
    max_tool_calls: int = 12

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_ms: int = 0

    stop_reason: Optional[str] = None
    final_status: str = "IN_PROGRESS"  # IN_PROGRESS, CONVERGED, STOPPED, FAILED, TIMEOUT

    physical_escalation_required: bool = False
    unknown_factors: List[str] = Field(default_factory=list)
    rejected_escalations: List[str] = Field(default_factory=list)

    def record_rejected_escalation(self, reason: str) -> None:
        """记录被安全防护拦截的物理升级请求"""
        self.rejected_escalations.append(reason)
        self.unknown_factors.append(f"物理升级请求被拦截: {reason}")

    def add_evidence(self, record: EvidenceRecord) -> None:
        """追加一条客观证据记录"""
        self.evidence.append(record)

    def record_step_execution(self, step: InvestigationStep, is_failed: bool = False) -> None:
        """记录步骤执行与资源消耗"""
        self.tool_calls += 1
        if is_failed:
            self.failed_steps.append(step)
        else:
            self.executed_steps.append(step)

    def is_budget_exhausted(self) -> bool:
        """预算是否耗尽"""
        return self.iteration >= self.max_iterations or self.tool_calls >= self.max_tool_calls

    def get_confirmed_evidence(self) -> List[EvidenceRecord]:
        """获取所有高可靠客观证据"""
        return [e for e in self.evidence if not e.is_error and e.reliability >= 0.8]

    def has_tool_failure(self) -> bool:
        """是否存在工具执行失败（观测缺口）"""
        return len(self.failed_steps) > 0 or any(e.is_error for e in self.evidence)
