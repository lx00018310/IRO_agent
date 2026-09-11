from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class EvalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    INFRA_ERROR = "INFRA_ERROR"


class EvalExpectation(BaseModel):
    acceptable_root_causes: List[str] = Field(default_factory=list)
    required_evidence_types: List[str] = Field(default_factory=list)
    forbidden_claims: List[str] = Field(default_factory=list)
    required_behavior: List[str] = Field(default_factory=list)
    forbidden_actions: List[str] = Field(default_factory=list)


class EvalGradingWeights(BaseModel):
    root_cause_weight: float = 0.30
    evidence_weight: float = 0.25
    path_weight: float = 0.15
    abstention_weight: float = 0.10
    safety_weight: float = 0.20


class EvalCase(BaseModel):
    case_id: str
    case_version: int = 1
    category: str = "general"
    severity: str = "medium"
    input: Dict[str, Any] = Field(default_factory=dict)
    fixture: Dict[str, Any] = Field(default_factory=dict)
    expectation: EvalExpectation = Field(default_factory=EvalExpectation)
    grading: EvalGradingWeights = Field(default_factory=EvalGradingWeights)


class GradeDetail(BaseModel):
    name: str
    score: float = 1.0  # 0.0 ~ 1.0
    passed: bool = True
    details: str = ""
    violations: List[str] = Field(default_factory=list)


class CaseEvalResult(BaseModel):
    case_id: str
    status: EvalStatus
    final_score: float = 0.0
    root_cause_score: float = 0.0
    evidence_score: float = 0.0
    path_score: float = 0.0
    safety_score: float = 1.0
    abstention_score: float = 0.0
    unsupported_claim_count: int = 0
    tool_call_count: int = 0
    iteration_count: int = 0
    duration_ms: int = 0
    stop_reason: str = ""
    final_answer: str = ""
    trajectory_path: Optional[str] = None
    grade_details: List[GradeDetail] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    run_id: str
    dataset_type: str
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    error_cases: int = 0
    average_score: float = 0.0
    safety_violations: int = 0
    results: List[CaseEvalResult] = Field(default_factory=list)
