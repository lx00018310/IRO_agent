from typing import List, Dict, Any, Optional
from datetime import datetime


class TimelineEvent:
    def __init__(self, timestamp: str, source: str, event: str, evidence: str, is_confirmed: bool = True):
        self.timestamp = timestamp
        self.source = source
        self.event = event
        self.evidence = evidence
        self.is_confirmed = is_confirmed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "event": self.event,
            "evidence": self.evidence,
            "is_confirmed": self.is_confirmed,
        }


class TimelineBuilder:
    """事件时间线聚合器：按时间顺序串联部署记录、日志异动、代码提交与现场反馈"""

    def __init__(self):
        self.events: List[TimelineEvent] = []

    def add_event(self, timestamp: str, source: str, event: str, evidence: str, is_confirmed: bool = True) -> None:
        if not timestamp:
            return
        self.events.append(TimelineEvent(timestamp, source, event, evidence, is_confirmed))

    def build(self) -> List[Dict[str, Any]]:
        """按时间戳升序排序并输出结构化时间线列表"""
        # 归一化排序
        sorted_events = sorted(self.events, key=lambda e: str(e.timestamp))
        return [e.to_dict() for e in sorted_events]

    def render_markdown(self) -> str:
        """生成 Markdown 格式的业务时间线展示文本"""
        events = self.build()
        if not events:
            return "暂无可确认的有效时间线数据。"

        lines = ["| 时间 | 来源 | 事件描述 | 状态 / 凭证 |", "|---|---|---|---|"]
        for ev in events:
            conf = "已确认" if ev["is_confirmed"] else "推断"
            time_display = ev["timestamp"].replace("T", " ")[:19]
            lines.append(f"| {time_display} | {ev['source']} | {ev['event']} | [{conf}] {ev['evidence']} |")
        return "\n".join(lines)
