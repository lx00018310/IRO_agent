import json
import re
import logging
from typing import List, Optional, Dict, Any, Tuple
from iro_agent.llm.glm_client import GlmClient
from iro_agent.investigation.models import (
    PlannerDecision,
    DecisionAction,
    Hypothesis,
    EvidenceRecord,
    HypothesisStatus,
)
from iro_agent.investigation.tool_registry import ToolRegistry
from iro_agent.investigation.planner_validator import PlannerValidator

logger = logging.getLogger(__name__)


class LLMInvestigationPlanner:
    """
    LLM 现场故障排查智能规划器 (Agentic LLM Investigation Planner)
    基于最新观察状态与证据链，逐轮进行推理与下一步最佳动作规划 (Next-Best-Evidence Replanning)。
    输出结构化 JSON 决策，内置只读安全硬约束、格式验证与自我纠错重试机制。
    """

    SYSTEM_PROMPT = """你是一个工业自动化与现场系统（PLC、机器人、调度系统、数据库、中间件）排查诊断专家。
当前正在进行故障假设驱动排查。你必须严格基于客观证据推进，绝对禁止凭空臆测，严禁使用任何破坏性或写操作指令。

【当前排查目标与上下文】
- 故障现象 (Symptom): {symptom}
- 剩余行动预算步数: {remaining_budget}

【当前排查假设状态】
{hypotheses_text}

【已采集的客观事实证据】
{evidence_text}

【当前允许调用的只读安全工具白名单】
{tools_text}

【决策动作规则】
1. EXECUTE_TOOL: 当需要继续采集证据以验证/推翻某个假设时选择。必须指定 tool_name、tool_arguments 和 target_hypothesis。
2. CONVERGE: 当已有充分关键证据（如日志明确抛出异常根本原因、数据库数据状态明确证实）足以结案时选择。
3. ESCALATE_PHYSICAL: 当数字系统层（代码/日志/DB/配置/网络）均未发现异常，推断可能为现场物理电气/机械故障（如急停拍下、光电传感器脏污遮挡、伺服抱闸、硬件接线松动）时选择。
4. GIVE_UP: 当预算耗尽或缺乏有效可查维度时选择。

【输出格式硬性要求】
你必须且仅输出一个合法的 JSON 格式对象，严禁包含任何其他无关文本。格式如下：
```json
{{
  "thought": "你的现场排查逻辑推导与思考过程",
  "decision": "EXECUTE_TOOL",
  "target_hypothesis": "假设ID",
  "tool_name": "工具名称",
  "tool_arguments": {{ "arg1": "value1" }},
  "reason": "执行该操作的排查目的"
}}
```
"""

    def __init__(
        self,
        glm_client: Optional[GlmClient] = None,
        registry: Optional[ToolRegistry] = None,
        validator: Optional[PlannerValidator] = None,
    ):
        self.glm_client = glm_client or GlmClient()
        self.registry = registry or ToolRegistry()
        self.validator = validator or PlannerValidator(registry=self.registry)

    def plan_next_step(
        self,
        symptom: str,
        hypotheses: List[Hypothesis],
        evidence_history: Optional[List[EvidenceRecord]] = None,
        remaining_budget: int = 10,
        max_retries: int = 1,
    ) -> PlannerDecision:
        """
        根据当前状态，让 LLM 规划下一步动作
        """
        evidence_records = evidence_history or []
        user_prompt = self._build_prompt(
            symptom=symptom,
            hypotheses=hypotheses,
            evidence_records=evidence_records,
            remaining_budget=remaining_budget,
        )

        messages = [
            {"role": "system", "content": "你是一个严谨的工业故障诊断决策规划器，只能输出规范的单一 JSON 对象。"},
            {"role": "user", "content": user_prompt},
        ]

        attempt = 0
        while attempt <= max_retries:
            attempt += 1
            try:
                raw_reply = self.glm_client.chat_completion(messages, verbose=False)
            except Exception as e:
                logger.error(f"[LLMPlanner] 模型调用异常: {e}")
                return PlannerDecision(
                    thought="调用大模型发生通信异常",
                    decision=DecisionAction.CONVERGE,
                    error=f"PLANNER_ERROR: 模型调用失败 - {e}",
                )

            decision, parse_err = self._parse_json_reply(raw_reply)
            if parse_err:
                logger.warning(f"[LLMPlanner] 第 {attempt} 次解析 JSON 失败: {parse_err}")
                if attempt <= max_retries:
                    messages.append({"role": "assistant", "content": raw_reply or ""})
                    messages.append({
                        "role": "user",
                        "content": f"你输出的内容无法解析为合法 JSON 决策: {parse_err}。请严格按照 schema 重新输出唯一的合法 JSON 对象！",
                    })
                    continue
                else:
                    return PlannerDecision(
                        thought="LLM 输出无法解析为 JSON，触发安全兜底",
                        decision=DecisionAction.CONVERGE,
                        error=f"PLANNER_ERROR: {parse_err}",
                    )

            # 严格验证决策合法性
            is_valid, val_err = self.validator.validate(decision, hypotheses)
            if not is_valid:
                logger.warning(f"[LLMPlanner] 第 {attempt} 次决策校验未通过: {val_err}")
                if attempt <= max_retries:
                    messages.append({"role": "assistant", "content": raw_reply or ""})
                    messages.append({
                        "role": "user",
                        "content": f"你的决策未通过安全或规范校验: {val_err}。请纠正并重新输出合法 JSON！",
                    })
                    continue
                else:
                    return PlannerDecision(
                        thought="LLM 决策多次校验未通过，触发安全兜底",
                        decision=DecisionAction.CONVERGE,
                        error=f"PLANNER_ERROR: {val_err}",
                    )

            # 校验通过
            return decision

        return PlannerDecision(
            thought="超过最大重试次数，安全结束",
            decision=DecisionAction.CONVERGE,
            error="PLANNER_ERROR: 超过最大重试次数",
        )

    def _build_prompt(
        self,
        symptom: str,
        hypotheses: List[Hypothesis],
        evidence_records: List[EvidenceRecord],
        remaining_budget: int,
    ) -> str:
        # 格式化假设列表
        hypo_lines = []
        for h in hypotheses:
            status_str = f"[{h.status.value}]" if hasattr(h.status, "value") else f"[{h.status}]"
            hypo_lines.append(f"- {h.hypothesis_id}: {status_str} {h.description}")
            if h.supporting_evidence:
                hypo_lines.append(f"  支持证据: {h.supporting_evidence}")
            if h.contradicting_evidence:
                hypo_lines.append(f"  反驳证据: {h.contradicting_evidence}")
        hypotheses_text = "\n".join(hypo_lines) if hypo_lines else "（暂无活动假设）"

        # 格式化已收集的证据
        ev_lines = []
        for ev in evidence_records:
            tier_val = ev.tier.value if hasattr(ev.tier, "value") else str(ev.tier)
            ev_lines.append(f"- [{tier_val}] {ev.source_name}: {ev.raw_summary}")
        evidence_text = "\n".join(ev_lines) if ev_lines else "（尚未采集到客观证据）"

        # 格式化工具列表
        tools_text = self.registry.get_prompt_description()

        return self.SYSTEM_PROMPT.format(
            symptom=symptom,
            remaining_budget=remaining_budget,
            hypotheses_text=hypotheses_text,
            evidence_text=evidence_text,
            tools_text=tools_text,
        )

    def _parse_json_reply(self, reply_text: str) -> Tuple[Optional[PlannerDecision], Optional[str]]:
        if not reply_text or not reply_text.strip():
            return None, "模型返回内容为空"

        text = reply_text.strip()
        # 尝试匹配 ```json ... ``` 块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            raw_json = match.group(1).strip()
        else:
            # 尝试直接定位首尾大括号
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw_json = text[start : end + 1]
            else:
                raw_json = text

        try:
            data = json.loads(raw_json)
        except Exception as e:
            return None, f"JSON 反序列化失败 ({e})，原始内容: {raw_json[:100]}"

        if not isinstance(data, dict):
            return None, "JSON 根节点必须为键值对对象 (Dict)"

        try:
            decision = PlannerDecision(**data)
            return decision, None
        except Exception as e:
            return None, f"决策结构体契约校验失败: {e}"
