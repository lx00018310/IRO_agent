from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class KnowledgeUnknown:
    """项目认知中的未知暗区与疑问一等对象 (First-class Unknown)"""
    unknown_id: str
    topic: str
    description: str
    importance: int = 3  # 1 ~ 5
    resolvability: int = 3  # 0: UNRESOLVABLE_DIGITALLY, 1~5
    evidence_gap: str = ""
    suggested_sources: List[str] = field(default_factory=list)
    attempted_sources: List[str] = field(default_factory=list)
    status: str = "OPEN"  # OPEN, PARTIALLY_RESOLVED, RESOLVED, UNRESOLVABLE_DIGITALLY, CONTRADICTED

    category: str = "architecture"  # architecture, modules, business_flows, state_machines, database, config, integrations, observability
    business_impact: float = 1.0  # 0.0 ~ 1.0
    diagnostic_relevance: float = 1.0  # 0.0 ~ 1.0
    confidence_gap: float = 1.0  # 0.0 ~ 1.0 (已获取证据越少，gap 越大)
    reading_cost: float = 1.0  # 预估阅读耗费/开销 (>= 0.1)

    resolution_notes: str = ""
    resolved_in_round: Optional[int] = None

    def calculate_priority(self) -> float:
        """
        动态计算未知暗区解决优先级
        priority = business_impact * diagnostic_relevance * resolvability * confidence_gap / reading_cost
        对于已解决、矛盾或数字不可解的项，优先级为 0
        """
        if self.status in ("RESOLVED", "CONTRADICTED", "UNRESOLVABLE_DIGITALLY"):
            return 0.0
        if self.resolvability <= 0:
            return 0.0

        cost = max(self.reading_cost, 0.1)
        score = (
            self.business_impact
            * self.diagnostic_relevance
            * float(self.resolvability)
            * self.confidence_gap
        ) / cost
        return round(score, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unknown_id": self.unknown_id,
            "topic": self.topic,
            "description": self.description,
            "importance": self.importance,
            "resolvability": self.resolvability,
            "evidence_gap": self.evidence_gap,
            "suggested_sources": self.suggested_sources,
            "attempted_sources": self.attempted_sources,
            "status": self.status,
            "category": self.category,
            "business_impact": self.business_impact,
            "diagnostic_relevance": self.diagnostic_relevance,
            "confidence_gap": self.confidence_gap,
            "reading_cost": self.reading_cost,
            "priority": self.calculate_priority(),
            "resolution_notes": self.resolution_notes,
            "resolved_in_round": self.resolved_in_round,
        }


class UnknownQueue:
    """未知暗区优先级调度队列"""

    def __init__(self, items: Optional[List[KnowledgeUnknown]] = None):
        self._items: Dict[str, KnowledgeUnknown] = {}
        if items:
            for item in items:
                self.add(item)

    def add(self, unknown: KnowledgeUnknown) -> None:
        self._items[unknown.unknown_id] = unknown

    def get(self, unknown_id: str) -> Optional[KnowledgeUnknown]:
        return self._items.get(unknown_id)

    def all_items(self) -> List[KnowledgeUnknown]:
        return list(self._items.values())

    def get_open_items(self) -> List[KnowledgeUnknown]:
        return [
            u for u in self._items.values()
            if u.status in ("OPEN", "PARTIALLY_RESOLVED") and u.resolvability > 0
        ]

    def pop_highest_priority(self) -> Optional[KnowledgeUnknown]:
        """选出当前优先级最高的待解决未知暗区"""
        open_items = self.get_open_items()
        if not open_items:
            return None
        sorted_items = sorted(open_items, key=lambda x: x.calculate_priority(), reverse=True)
        top = sorted_items[0]
        if top.calculate_priority() <= 0:
            return None
        return top

    def mark_attempted(self, unknown_id: str, source: str) -> None:
        item = self._items.get(unknown_id)
        if item and source not in item.attempted_sources:
            item.attempted_sources.append(source)

    def resolve(self, unknown_id: str, notes: str = "", round_no: Optional[int] = None) -> None:
        item = self._items.get(unknown_id)
        if item:
            item.status = "RESOLVED"
            item.confidence_gap = 0.0
            item.resolution_notes = notes
            item.resolved_in_round = round_no

    def mark_unresolvable(self, unknown_id: str, notes: str = "") -> None:
        item = self._items.get(unknown_id)
        if item:
            item.status = "UNRESOLVABLE_DIGITALLY"
            item.resolvability = 0
            item.resolution_notes = notes

    def mark_partially_resolved(self, unknown_id: str, gap_remaining: float, notes: str = "") -> None:
        item = self._items.get(unknown_id)
        if item:
            item.status = "PARTIALLY_RESOLVED"
            item.confidence_gap = max(0.1, min(1.0, gap_remaining))
            if notes:
                item.resolution_notes = f"{item.resolution_notes}; {notes}".strip("; ")

    def all_digitally_unresolvable_or_resolved(self) -> bool:
        """检查是否所有开放项都已解决或不可解"""
        for u in self._items.values():
            if u.status in ("OPEN", "PARTIALLY_RESOLVED") and u.resolvability > 0:
                return False
        return True

    def count_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for u in self._items.values():
            counts[u.status] = counts.get(u.status, 0) + 1
        return counts
