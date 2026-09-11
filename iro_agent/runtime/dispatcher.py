import logging
from typing import Dict, Any, Optional
from iro_agent.config import IROConfig, get_config
from iro_agent.router.intent_router import IntentRouter, QueryIntent
from iro_agent.investigation.harness import InvestigationHarness
from iro_agent.investigation.models import InvestigationReport
from iro_agent.llm.glm_client import GlmClient
from iro_agent.runtime.models import RuntimeRoute, DispatchResult
from iro_agent.memory.learning_store import LearningMemoryStore

logger = logging.getLogger(__name__)


class RuntimeDispatcher:
    """企业级统一运行时消息与故障分发器 (Unified Runtime Dispatcher)"""

    def __init__(
        self,
        config: Optional[IROConfig] = None,
        harness: Optional[InvestigationHarness] = None,
        glm_client: Optional[GlmClient] = None,
        learning_store: Optional[LearningMemoryStore] = None,
    ):
        self.config = config or get_config()
        self.harness = harness or InvestigationHarness()
        self.glm_client = glm_client
        self.learning_store = learning_store or LearningMemoryStore()

    def determine_route(self, message: str, context: Optional[Dict[str, Any]] = None) -> RuntimeRoute:
        """判定提问意图归属路由"""
        ctx = context or {}
        if ctx.get("force_route"):
            return RuntimeRoute(ctx["force_route"])

        msg_clean = (message or "").strip()
        if not msg_clean:
            return RuntimeRoute.GENERAL_CHAT

        msg_lower = msg_clean.lower()

        # 排除咨询类问句（例如“有什么异常吗”、“今天有什么异常”、“有没有报错”、“什么意思”）
        query_exception_markers = ["有什么异常", "有没有异常", "是否有异常", "有什么问题", "有没有报错", "是否有报错", "什么意思", "什么含义"]
        if any(qm in msg_lower for qm in query_exception_markers):
            return RuntimeRoute.FACT_QUERY

        # 意图路由识别
        intent_res = IntentRouter.route(msg_clean)
        intent = intent_res.get("intent")

        if intent == QueryIntent.RUNTIME_FAULT:
            return RuntimeRoute.RUNTIME_FAULT

        # 静态事实/表结构/配置/版本判定（优先级高于兜底故障动词）
        fact_markers = ["几个", "有哪些", "定义", "字段", "表结构", "哪张表", "表有", "说明", "规则是什么", "最新版本", "配置项", "版本是多少"]
        if any(fm in msg_lower for fm in fact_markers):
            return RuntimeRoute.FACT_QUERY

        # 兜底检测强故障动词
        fault_markers = [
            "卡死", "卡住", "不动了", "不走", "停止", "报错", "异常",
            "掉线", "中断", "失败", "超时", "死锁", "坏了", "为什么",
            "408", "500", "502", "npe", "connection reset"
        ]
        if any(m in msg_lower for m in fault_markers):
            return RuntimeRoute.RUNTIME_FAULT

        if intent in (QueryIntent.CONFIGURATION, QueryIntent.BUSINESS_DATA, QueryIntent.CODE_STRUCTURE, QueryIntent.VERSION, QueryIntent.HISTORY):
            return RuntimeRoute.FACT_QUERY

        return RuntimeRoute.GENERAL_CHAT

    def dispatch(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> DispatchResult:
        """
        统一分发执行：
        - RUNTIME_FAULT: 强制接入 InvestigationHarness 闭环
        - FACT_QUERY / GENERAL_CHAT: 走通用只读辅助问答通道
        """
        route = self.determine_route(message, context)
        ctx = context or {}
        image_path = ctx.get("image_path")
        history = ctx.get("history")

        if route == RuntimeRoute.RUNTIME_FAULT:
            logger.info(f"[RuntimeDispatcher] Routing '{message[:30]}...' to InvestigationHarness")
            verbose = ctx.get("verbose", False)
            report = self.harness.investigate(symptom=message, verbose=verbose)
            reply_text = self._format_investigation_human_report(report)
            return DispatchResult(
                route=RuntimeRoute.RUNTIME_FAULT,
                reply_text=reply_text,
                investigation_report=report,
                session_id=session_id,
                metadata={"case_id": report.case_id, "case_type": report.case_type.value},
            )

        elif route == RuntimeRoute.FACT_QUERY:
            logger.info(f"[RuntimeDispatcher] Routing '{message[:30]}...' to FACT_QUERY general agent")
            reply_text = self._handle_general_query(message, session_id=session_id, is_fact=True, image_path=image_path, history=history)
            return DispatchResult(
                route=RuntimeRoute.FACT_QUERY,
                reply_text=reply_text,
                investigation_report=None,
                session_id=session_id,
            )

        else:
            logger.info(f"[RuntimeDispatcher] Routing '{message[:30]}...' to GENERAL_CHAT")
            reply_text = self._handle_general_query(message, session_id=session_id, is_fact=False, image_path=image_path, history=history)
            return DispatchResult(
                route=RuntimeRoute.GENERAL_CHAT,
                reply_text=reply_text,
                investigation_report=None,
                session_id=session_id,
            )

    def _format_investigation_human_report(self, report: InvestigationReport) -> str:
        """根据标准规范将内部排查报告格式化为清晰的人类业务报告"""
        lines = []
        lines.append("【核心排查结论】")
        lines.append(report.root_cause or "未定位到明确单点故障原因。")
        lines.append("")

        if report.key_evidence:
            lines.append("【关键事实依据】")
            for ev in report.key_evidence[:5]:
                lines.append(f"- {ev}")
            lines.append("")

        if report.unknown_factors:
            lines.append("【当前未确认项与观测盲区】")
            for uk in report.unknown_factors[:3]:
                lines.append(f"- {uk}")
            lines.append("")

        actions = getattr(report, "recommended_actions", None) or getattr(report, "physical_escalation_checklist", [])
        if actions:
            lines.append("【建议下一步处置】")
            for act in actions[:3]:
                lines.append(f"- {act}")
        elif getattr(report, "physical_escalation_required", False):
            lines.append("【建议下一步处置】")
            lines.append("- 数字系统运行正常，建议现场电气/机械工程师检查硬件接线、供电或物理闭锁状态。")

        return "\n".join(lines).strip()

    def _handle_general_query(
        self,
        message: str,
        session_id: Optional[str] = None,
        is_fact: bool = True,
        image_path: Optional[str] = None,
        history: Optional[list] = None,
    ) -> str:
        """处理通用事实查询或日常交流"""
        if self.glm_client:
            msgs = list(history) if history else [{"role": "user", "content": message}]
            try:
                try:
                    res = self.glm_client.chat_completion(msgs, image_path=image_path, verbose=False)
                except TypeError:
                    res = self.glm_client.chat_completion(msgs, verbose=False)
                return str(res) if res is not None else ""
            except Exception as e:
                logger.error(f"General query error: {e}")
                return f"查询处理异常: {e}"
        return f"已收到查询: {message}。当前处于只读安全环境，未连接外部会话大模型。"
