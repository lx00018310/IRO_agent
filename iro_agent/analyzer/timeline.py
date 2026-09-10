import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime


class TimelineEvent:
    """统一时序事件模型：标准化来自版本提供者、日志、数据库、会话与历史记忆的证据事件"""

    def __init__(
        self,
        timestamp: str,
        source_type: str,
        event_type: str,
        title: str,
        detail: str = "",
        evidence_level: str = "CONFIRMED",
        project: str = "",
        source_id: str = "",
        event_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        # 兼容旧构造函数参数
        source: Optional[str] = None,
        event: Optional[str] = None,
        evidence: Optional[str] = None,
        is_confirmed: Optional[bool] = None,
    ):
        self.event_id = event_id or f"EVT-{uuid.uuid4().hex[:8]}"
        self.project = project
        self.timestamp = timestamp or ""
        self.source_type = (source or source_type).lower()
        self.event_type = event_type or "general_event"
        self.title = event or title
        self.detail = evidence or detail
        if is_confirmed is not None:
            self.evidence_level = "CONFIRMED" if is_confirmed else "INFERRED"
        else:
            self.evidence_level = evidence_level.upper() if evidence_level else "CONFIRMED"
        self.source_id = source_id
        self.metadata = metadata or {}

    @property
    def is_confirmed(self) -> bool:
        return self.evidence_level == "CONFIRMED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project": self.project,
            "timestamp": self.timestamp,
            "source_type": self.source_type,
            "event_type": self.event_type,
            "title": self.title,
            "detail": self.detail,
            "evidence_level": self.evidence_level,
            "source_id": self.source_id,
            "metadata": self.metadata,
            # 兼容字段
            "source": self.source_type.capitalize(),
            "event": self.title,
            "evidence": self.detail,
            "is_confirmed": self.is_confirmed,
        }


class TimelineBuilder:
    """事件时间线聚合器：按时间戳严格排序归一化，合并各路证据事件"""

    def __init__(self, project_name: str = ""):
        self.project_name = project_name
        self.events: List[TimelineEvent] = []

    def add_event(
        self,
        timestamp: str,
        source: str,
        event: str,
        evidence: str = "",
        is_confirmed: bool = True,
        event_type: str = "observation",
        source_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TimelineEvent:
        """添加通用时序事件（向后兼容老接口）"""
        if not timestamp:
            return None
        lvl = "CONFIRMED" if is_confirmed else "INFERRED"
        evt = TimelineEvent(
            timestamp=timestamp,
            source_type=source,
            event_type=event_type,
            title=event,
            detail=evidence,
            evidence_level=lvl,
            project=self.project_name,
            source_id=source_id,
            metadata=metadata,
        )
        self.events.append(evt)
        return evt

    def add_conversation_event(
        self,
        timestamp: str,
        role: str,
        message: str,
        session_id: str = "",
    ) -> TimelineEvent:
        """记录用户提问与系统回答的发生时间，使人机沟通成为时间线确凿证据"""
        title = f"现场人员报告: {message[:50]}" if role == "user" else f"助手诊断响应: {message[:50]}"
        return self.add_event(
            timestamp=timestamp,
            source="conversation",
            event=title,
            evidence=f"会话角色: {role} (消息长度 {len(message)})",
            is_confirmed=True,
            event_type="user_report" if role == "user" else "agent_reply",
            metadata={"role": role, "full_text": message, "session_id": session_id},
        )

    def build(self) -> List[Dict[str, Any]]:
        """按时间戳升序排序并输出结构化时间线列表"""
        sorted_events = sorted(self.events, key=lambda e: str(e.timestamp))
        return [e.to_dict() for e in sorted_events]

    def render_markdown(self) -> str:
        """生成 Markdown 格式的业务时间线展示文本"""
        events = self.build()
        if not events:
            return "暂无可确认的有效时间线数据。"

        lines = ["| 时间 | 来源 | 事件描述 | 状态 / 凭证 |", "|---|---|---|---|"]
        for ev in events:
            lvl_tag = "已确认" if ev["evidence_level"] == "CONFIRMED" else (
                "推断" if ev["evidence_level"] == "INFERRED" else "未知"
            )
            time_display = ev["timestamp"].replace("T", " ")[:19]
            source_display = ev.get("source") or ev.get("source_type", "unknown").capitalize()
            lines.append(f"| {time_display} | {source_display} | {ev['title']} | [{lvl_tag}] {ev['detail']} |")
        return "\n".join(lines)
