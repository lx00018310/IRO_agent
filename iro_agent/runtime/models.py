from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from iro_agent.investigation.models import InvestigationReport


class RuntimeRoute(str, Enum):
    """统一运行时请求路由枚举"""
    RUNTIME_FAULT = "RUNTIME_FAULT"
    FACT_QUERY = "FACT_QUERY"
    PROJECT_LEARNING = "PROJECT_LEARNING"
    GENERAL_CHAT = "GENERAL_CHAT"


class DispatchResult(BaseModel):
    """运行时统一分发处理结果"""
    route: RuntimeRoute
    reply_text: Any = ""
    investigation_report: Optional[InvestigationReport] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not isinstance(self.reply_text, str):
            self.reply_text = str(self.reply_text) if self.reply_text is not None else ""
