from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.unknowns import KnowledgeUnknown, UnknownQueue


# 标准 10 维知识覆盖率定义
DEFAULT_COVERAGE_DIMENSIONS = [
    "architecture",
    "modules",
    "business_flows",
    "state_machines",
    "database_source_of_truth",
    "config_effective_path",
    "external_integrations",
    "runtime_observability",
    "version_release",
    "known_unknowns",
]


@dataclass
class LearningState:
    """项目认知学习状态一等对象 (Knowledge Learning State)"""
    confirmed_facts: List[Dict[str, Any]] = field(default_factory=list)
    inferred_facts: List[Dict[str, Any]] = field(default_factory=list)
    unknowns: List[KnowledgeUnknown] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)

    completed_reads: List[Dict[str, Any]] = field(default_factory=list)
    failed_reads: List[Dict[str, Any]] = field(default_factory=list)

    coverage: Dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in DEFAULT_COVERAGE_DIMENSIONS})
    coverage_history: List[float] = field(default_factory=list)  # 记录每轮 overall coverage

    round_no: int = 0
    max_rounds: int = 12

    glm_calls: int = 0
    token_or_cost_stats: Dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_cost": 0.0,
    })

    stop_reason: Optional[str] = None

    def get_unknown_queue(self) -> UnknownQueue:
        return UnknownQueue(self.unknowns)

    def sync_unknown_queue(self, queue: UnknownQueue) -> None:
        self.unknowns = queue.all_items()

    def overall_coverage(self) -> float:
        """计算 10 维度的总体平均覆盖率"""
        if not self.coverage:
            return 0.0
        return round(sum(self.coverage.values()) / len(self.coverage), 4)

    def update_coverage_dimension(self, dimension: str, value: float) -> None:
        """更新单个维度覆盖率 (0.0 ~ 1.0)"""
        clamped = max(0.0, min(1.0, float(value)))
        self.coverage[dimension] = round(clamped, 4)

    def record_round_coverage(self) -> None:
        """记录当前轮次的 overall coverage 到历史列表"""
        self.coverage_history.append(self.overall_coverage())

    def recent_coverage_gains(self, window: int = 2) -> List[float]:
        """获取最近 window 轮的 coverage 增量"""
        if len(self.coverage_history) < 2:
            return []
        gains = []
        for i in range(1, len(self.coverage_history)):
            gains.append(round(self.coverage_history[i] - self.coverage_history[i - 1], 4))
        return gains[-window:]

    def add_fact(self, fact_text: str, source: str, confidence: str = "STRONGLY_SUPPORTED", details: Optional[Dict[str, Any]] = None) -> None:
        """添加知识事实，区分为确认或推断"""
        item = {
            "fact": fact_text,
            "source": source,
            "confidence": confidence,
            "round": self.round_no,
            "details": details or {},
        }
        if confidence == "CONFIRMED":
            self.confirmed_facts.append(item)
        else:
            self.inferred_facts.append(item)

    def add_contradiction(self, topic: str, statement_a: str, statement_b: str, sources: List[str]) -> None:
        """记录发现的矛盾事实"""
        self.contradictions.append({
            "topic": topic,
            "statement_a": statement_a,
            "statement_b": statement_b,
            "sources": sources,
            "round": self.round_no,
        })

    def record_read(self, source_path: str, lines: int, success: bool = True, error: Optional[str] = None) -> None:
        record = {
            "source_path": source_path,
            "lines": lines,
            "round": self.round_no,
            "success": success,
        }
        if success:
            self.completed_reads.append(record)
        else:
            record["error"] = error or "read_failed"
            self.failed_reads.append(record)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_no": self.round_no,
            "max_rounds": self.max_rounds,
            "overall_coverage": self.overall_coverage(),
            "coverage": self.coverage,
            "confirmed_facts_count": len(self.confirmed_facts),
            "inferred_facts_count": len(self.inferred_facts),
            "unknowns_count": len(self.unknowns),
            "contradictions_count": len(self.contradictions),
            "completed_reads_count": len(self.completed_reads),
            "failed_reads_count": len(self.failed_reads),
            "glm_calls": self.glm_calls,
            "token_or_cost_stats": self.token_or_cost_stats,
            "stop_reason": self.stop_reason,
            "unknowns": [u.to_dict() for u in self.unknowns],
            "contradictions": self.contradictions,
        }
