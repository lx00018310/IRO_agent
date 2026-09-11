from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class EvidenceTier(str, Enum):
    """证据优先级层级 (Evidence Priority Tiers)"""
    TIER_1A_RUNTIME_DIGITAL = "Tier 1A - 运行时数字事实 (日志/DB/生效配置/当前版本)"
    TIER_1B_STATIC_FACTS = "Tier 1B - 系统静态事实 (代码/状态机/业务流/协议定义)"
    TIER_2_SYSTEM_BOUNDARY = "Tier 2 - 系统边界通信 (API/PLC信号/机器人状态/报文)"
    TIER_3_RUNTIME_ENV = "Tier 3 - 运行环境要素 (进程/端口/CPU/内存/磁盘/网络)"
    TIER_4_PHYSICAL = "Tier 4 - 物理带外要素 (接线/光电/急停/供电/机械干涉)"


class CaseType(str, Enum):
    """排查案例类型 (Investigation Case Types)"""
    APPLICATION_ERROR = "APPLICATION_ERROR"
    DATA_STATE_ERROR = "DATA_STATE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    VERSION_CHANGE_ERROR = "VERSION_CHANGE_ERROR"
    INTERFACE_COMMUNICATION_ERROR = "INTERFACE_COMMUNICATION_ERROR"
    PLC_SIGNAL_ERROR = "PLC_SIGNAL_ERROR"
    ROBOT_EXECUTION_ERROR = "ROBOT_EXECUTION_ERROR"
    NETWORK_ENVIRONMENT_ERROR = "NETWORK_ENVIRONMENT_ERROR"
    UNKNOWN_RUNTIME_FAULT = "UNKNOWN_RUNTIME_FAULT"


class HypothesisStatus(str, Enum):
    """假设状态 (Hypothesis Status)"""
    CONFIRMED = "CONFIRMED"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    SUPPORTED = "SUPPORTED"
    UNRESOLVED = "UNRESOLVED"
    WEAK = "WEAK"
    RULED_OUT = "RULED_OUT"


class Hypothesis(BaseModel):
    """竞争性排查假设数据模型"""
    hypothesis_id: str
    description: str
    related_flow_step: str = ""
    status: HypothesisStatus = HypothesisStatus.UNRESOLVED
    confidence: str = "Medium"
    required_evidence: List[str] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    contradicting_evidence: List[str] = Field(default_factory=list)


class InvestigationStep(BaseModel):
    """排查步骤数据模型"""
    step_id: str
    hypothesis_ids: List[str] = Field(default_factory=list)
    evidence_tier: EvidenceTier
    evidence_type: str
    tool: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    reason: str
    priority: int = 50
    result: Optional[Any] = None
    evaluation: Optional[str] = None  # FACT, SUPPORTING, CONTRADICTING, INCONCLUSIVE, MISSING


class EvidenceEvaluationResult(BaseModel):
    """证据单项评估结果"""
    step_id: str
    verdict: str  # FACT, SUPPORTING, CONTRADICTING, INCONCLUSIVE, MISSING
    detail: str
    impacted_hypotheses: Dict[str, str] = Field(default_factory=dict)  # h_id -> new_status


class InvestigationReport(BaseModel):
    """排查结案综合报告"""
    case_type: CaseType
    symptom: str
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    primary_root_cause: Optional[str] = None
    confidence: str = "Medium"
    key_evidence: List[str] = Field(default_factory=list)
    investigation_trace: List[InvestigationStep] = Field(default_factory=list)
    physical_escalation_checklist: List[str] = Field(default_factory=list)
    stop_reason: str = ""
