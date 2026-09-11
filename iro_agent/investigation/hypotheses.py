import json
import re
import logging
from typing import List, Dict, Any, Optional
from iro_agent.investigation.models import (
    CaseType,
    Hypothesis,
    HypothesisStatus,
    HypothesisAction,
    HypothesisUpdate,
)
from iro_agent.llm.glm_client import GlmClient

logger = logging.getLogger(__name__)


def _invoke_structured_llm(glm_client: Any, prompt: str, system_prompt: str) -> str:
    """调用纯结构化 LLM 接口，与旧全局 SYSTEM_PROMPT 和 Tool Calling 完全隔离"""
    if hasattr(glm_client, "complete_structured"):
        res = glm_client.complete_structured(prompt=prompt, system_prompt=system_prompt)
        from unittest.mock import Mock
        if isinstance(res, Mock) and hasattr(glm_client, "chat_completion"):
            chat_res = glm_client.chat_completion(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                verbose=False,
            )
            if not isinstance(chat_res, Mock):
                return str(chat_res)
        return str(res) if res is not None else ""
    elif hasattr(glm_client, "chat_completion"):
        return glm_client.chat_completion(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            verbose=False,
        )
    return ""


class DynamicHypothesisGenerator:
    """
    LLM 动态竞争性假设推演生成器 (Dynamic Hypothesis Generator)
    由 LLM 根据现场真实故障表象 (Symptom) + 领域业务流程定义 (Flows) 动态推导生成 2~5 个互相排斥或竞争的根因假设。
    """

    PROMPT_TEMPLATE = """你是一个工业自动化与现场系统（PLC、机器人、调度系统、数据库、通信接口）排查归因专家。
请根据现场故障现象与已知业务流，推演提出 2~5 个具有竞争性、逻辑互斥且可验证的根因排查假设。

【现场故障现象 (Symptom)】:
{symptom}

【已知业务调度流】:
{flows_text}

【要求】:
1. 给出 2~5 个互斥的排查假设，覆盖系统边界(如网络/PLC/硬件)、业务逻辑层(如任务状态流转)、外部依赖等不同可能。
2. 每个假设包含：假设唯一ID (H1, H2, ...)、假设清晰描述 (description)、关联的流程环节 (related_flow_step)、需要检验的客观证据 (required_evidence 列表)。
3. 必须输出合法的单一 JSON 数组格式，严禁包含任何其他废话或解释说明。

格式示例:
```json
[
  {{
    "hypothesis_id": "H1",
    "description": "主任务记录未成功创建",
    "related_flow_step": "任务生成",
    "required_evidence": ["需要检验的客观证据1", "需要检验的客观证据2"]
  }}
]
```
"""

    @classmethod
    def generate_from_llm(
        cls,
        symptom: str,
        flows: Optional[List[Any]] = None,
        glm_client: Optional[GlmClient] = None,
    ) -> Optional[List[Hypothesis]]:
        """调用大模型动态生成竞争假设"""
        if not glm_client:
            return None

        flows_lines = []
        for f in flows or []:
            name = getattr(f, "name", str(f))
            desc = getattr(f, "description", "")
            flows_lines.append(f"- {name}: {desc}")
        flows_text = "\n".join(flows_lines) if flows_lines else "（标准出入库与现场工控调度流）"

        prompt = cls.PROMPT_TEMPLATE.format(symptom=symptom, flows_text=flows_text)
        sys_msg = "你是一个严谨的工业现场根因假设生成器，只能输出规范的单一 JSON 数组。"

        try:
            raw_reply = _invoke_structured_llm(
                glm_client,
                prompt=prompt,
                system_prompt=sys_msg,
            )
            if not raw_reply:
                return None

            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_reply.strip())
            if match:
                raw_json = match.group(1).strip()
            else:
                start = raw_reply.find("[")
                end = raw_reply.rfind("]")
                if start != -1 and end != -1 and end > start:
                    raw_json = raw_reply[start : end + 1]
                else:
                    raw_json = raw_reply

            data = json.loads(raw_json)
            if not isinstance(data, list) or not data:
                return None

            hypos: List[Hypothesis] = []
            for idx, item in enumerate(data, start=1):
                h_id = item.get("hypothesis_id") or f"H{idx}"
                desc = item.get("description") or f"动态假设 {h_id}"
                step = item.get("related_flow_step") or ""
                req_ev = item.get("required_evidence") or []
                hypos.append(Hypothesis(
                    hypothesis_id=h_id,
                    description=desc,
                    related_flow_step=step,
                    required_evidence=req_ev,
                    status=HypothesisStatus.UNRESOLVED,
                ))

            if len(hypos) >= 2:
                logger.info(f"[HypothesisGenerator] 成功由 LLM 动态推导生成 {len(hypos)} 个竞争假设")
                return hypos

        except Exception as e:
            logger.warning(f"[HypothesisGenerator] LLM 动态推导假设失败，将安全降级: {e}")

        return None


class HypothesisManager:
    """
    竞争性假设生命周期状态机管理器 (Hypothesis Lifecycle State Machine)
    支持：
    1. 初始假设的动态推演生成与确定性降级初始化；
    2. 假设生命周期的动态追加 (add)、动态修订 (revise) 与动态淘汰归档 (retire)；
    3. 状态跃迁流转 (UNRESOLVED -> SUPPORTED -> STRONGLY_SUPPORTED -> CONFIRMED / RULED_OUT)。
    """

    def __init__(
        self,
        case_type: Optional[CaseType] = None,
        symptom: str = "",
        flows: Optional[List[Any]] = None,
        initial_hypotheses: Optional[List[Hypothesis]] = None,
        glm_client: Optional[GlmClient] = None,
    ):
        self.case_type = case_type or CaseType.UNKNOWN_RUNTIME_FAULT
        self.symptom = symptom
        self.flows = flows or []
        self.glm_client = glm_client

        if initial_hypotheses:
            self.hypotheses = list(initial_hypotheses)
        else:
            # 优先尝试 LLM 动态生成
            dynamic_hypos = None
            if self.glm_client and self.symptom:
                dynamic_hypos = DynamicHypothesisGenerator.generate_from_llm(
                    symptom=self.symptom,
                    flows=self.flows,
                    glm_client=self.glm_client,
                )

            if dynamic_hypos:
                self.hypotheses = dynamic_hypos
                self.source = "llm_dynamic"
            else:
                self.hypotheses = self._generate_fallback_hypotheses()
                self.source = "deterministic_template"

    @property
    def active_hypotheses(self) -> List[Hypothesis]:
        """获取所有当前活跃未被排除的假设"""
        return [h for h in self.hypotheses if h.status != HypothesisStatus.RULED_OUT]

    @property
    def retired_hypotheses(self) -> List[Hypothesis]:
        """获取所有已被推翻淘汰的假设"""
        return [h for h in self.hypotheses if h.status == HypothesisStatus.RULED_OUT]

    def add_hypothesis(
        self,
        description: str,
        related_flow_step: str = "",
        required_evidence: Optional[List[str]] = None,
        hypothesis_id: Optional[str] = None,
    ) -> str:
        """
        在排查过程中动态追加新推导出的假设
        """
        existing_ids = {h.hypothesis_id for h in self.hypotheses}
        if not hypothesis_id or hypothesis_id in existing_ids:
            idx = len(self.hypotheses) + 1
            while f"H{idx}" in existing_ids:
                idx += 1
            hypothesis_id = f"H{idx}"

        new_h = Hypothesis(
            hypothesis_id=hypothesis_id,
            description=description,
            related_flow_step=related_flow_step,
            required_evidence=required_evidence or [],
            status=HypothesisStatus.UNRESOLVED,
        )
        self.hypotheses.append(new_h)
        logger.info(f"[HypothesisManager] 动态追加新假设 [{hypothesis_id}]: {description}")
        return hypothesis_id

    def retire_hypothesis(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> bool:
        """动态淘汰/排除某个假设"""
        return self.rule_out(hypothesis_id, reason, evidence)

    def revise_hypothesis(
        self,
        hypothesis_id: str,
        new_description: Optional[str] = None,
        new_required_evidence: Optional[List[str]] = None,
    ) -> bool:
        """动态修订假设的描述或检验证据要求"""
        h = self.get_hypothesis(hypothesis_id)
        if not h:
            return False
        if new_description:
            h.description = new_description
        if new_required_evidence is not None:
            h.required_evidence = list(new_required_evidence)
        logger.info(f"[HypothesisManager] 修订假设 [{hypothesis_id}] 内容")
        return True

    def get_hypothesis(self, h_id: str) -> Optional[Hypothesis]:
        for h in self.hypotheses:
            if h.hypothesis_id == h_id:
                return h
        return None

    def update_status(
        self,
        hypothesis_id: str,
        new_status: HypothesisStatus,
        reason: str,
        evidence: Optional[str] = None,
    ) -> bool:
        h = self.get_hypothesis(hypothesis_id)
        if not h:
            return False

        h.status = new_status
        if new_status in (HypothesisStatus.CONFIRMED, HypothesisStatus.STRONGLY_SUPPORTED, HypothesisStatus.SUPPORTED):
            if evidence and evidence not in h.supporting_evidence:
                h.supporting_evidence.append(evidence)
            h.confidence = "High" if new_status == HypothesisStatus.CONFIRMED else "Medium"
        elif new_status == HypothesisStatus.RULED_OUT:
            if evidence and evidence not in h.contradicting_evidence:
                h.contradicting_evidence.append(evidence)
            h.confidence = "RuledOut"
        return True

    def rule_out(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> bool:
        return self.update_status(hypothesis_id, HypothesisStatus.RULED_OUT, reason, evidence)

    def confirm(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> bool:
        return self.update_status(hypothesis_id, HypothesisStatus.CONFIRMED, reason, evidence)

    def strongly_support(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> bool:
        return self.update_status(hypothesis_id, HypothesisStatus.STRONGLY_SUPPORTED, reason, evidence)

    def apply_updates(
        self,
        updates: List[HypothesisUpdate],
        evidence_history: Optional[List[Any]] = None,
    ) -> List[str]:
        """
        受控执行来自 LLM Planner 的假设生命周期更新建议
        """
        applied: List[str] = []
        for upd in updates:
            action = upd.action
            if action == HypothesisAction.ADD:
                if upd.statement:
                    h_id = self.add_hypothesis(
                        description=upd.statement,
                        required_evidence=upd.evidence_ids,
                        hypothesis_id=upd.hypothesis_id,
                    )
                    applied.append(f"ADD:{h_id}")
            elif action == HypothesisAction.REVISE:
                if upd.hypothesis_id and self.revise_hypothesis(upd.hypothesis_id, new_description=upd.statement):
                    applied.append(f"REVISE:{upd.hypothesis_id}")
            elif action == HypothesisAction.RETIRE:
                if upd.hypothesis_id and self.retire_hypothesis(upd.hypothesis_id, reason=upd.reason or "LLM判定淘汰"):
                    applied.append(f"RETIRE:{upd.hypothesis_id}")
            elif action == HypothesisAction.SUPPORT:
                if upd.hypothesis_id:
                    new_status = (
                        HypothesisStatus.STRONGLY_SUPPORTED
                        if (upd.confidence is not None and upd.confidence >= 0.8)
                        else HypothesisStatus.SUPPORTED
                    )
                    ev_str = ", ".join(upd.evidence_ids) if upd.evidence_ids else (upd.reason or "")
                    if self.update_status(upd.hypothesis_id, new_status, reason=upd.reason, evidence=ev_str):
                        applied.append(f"SUPPORT:{upd.hypothesis_id}")
            elif action == HypothesisAction.CONTRADICT:
                if upd.hypothesis_id:
                    new_status = (
                        HypothesisStatus.RULED_OUT
                        if (upd.confidence is not None and upd.confidence <= 0.15)
                        else HypothesisStatus.WEAK
                    )
                    ev_str = ", ".join(upd.evidence_ids) if upd.evidence_ids else (upd.reason or "")
                    if self.update_status(upd.hypothesis_id, new_status, reason=upd.reason, evidence=ev_str):
                        applied.append(f"CONTRADICT:{upd.hypothesis_id}")
            elif action == HypothesisAction.MERGE:
                if upd.hypothesis_id:
                    self.retire_hypothesis(upd.hypothesis_id, reason=f"合并假设: {upd.reason}")
                    applied.append(f"MERGE:{upd.hypothesis_id}")
        return applied

    def get_top_hypothesis(self) -> Optional[Hypothesis]:
        """获取当前综合评级最高的活动假设"""
        order = {
            HypothesisStatus.CONFIRMED: 10,
            HypothesisStatus.STRONGLY_SUPPORTED: 8,
            HypothesisStatus.SUPPORTED: 5,
            HypothesisStatus.UNRESOLVED: 2,
            HypothesisStatus.WEAK: 1,
            HypothesisStatus.RULED_OUT: 0,
        }
        active = self.active_hypotheses
        if not active:
            return None
        return max(active, key=lambda h: (order.get(h.status, 0), len(h.supporting_evidence)))

    def has_confirmed_hypothesis(self) -> bool:
        return any(h.status == HypothesisStatus.CONFIRMED for h in self.hypotheses)

    def has_strongly_supported_hypothesis(self) -> bool:
        return any(h.status == HypothesisStatus.STRONGLY_SUPPORTED for h in self.hypotheses)

    def _generate_fallback_hypotheses(self) -> List[Hypothesis]:
        """离线或确定性降级保障：依据故障类别与业务流链条生成初始竞争性假设 (2~5个)"""
        hypos: List[Hypothesis] = []

        if self.case_type == CaseType.ROBOT_EXECUTION_ERROR:
            hypos.append(
                Hypothesis(
                    hypothesis_id="H1",
                    description="后端未成功接收或未识别上游/PLC触发信号",
                    related_flow_step="信号接收与校验",
                    required_evidence=["PLC通信日志", "后端入站请求记录"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H2",
                    description="后端收到信号但未成功创建或持久化出库/月台主任务",
                    related_flow_step="任务创建与持久化",
                    required_evidence=["dock_task主表记录", "调度服务日志"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H3",
                    description="后端已创建任务但向机器人/AGV发送调度指令失败或超时",
                    related_flow_step="向机器人下发指令",
                    required_evidence=["机器人API调用日志", "网络通信报文"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H4",
                    description="机器人已接收任务但因状态闭锁/未就绪拒绝执行",
                    related_flow_step="机器人就绪与执行",
                    required_evidence=["机器人状态回执", "设备健康日志"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H5",
                    description="现场物理/急停/光电传感器硬互锁或机械卡阻阻止移动",
                    related_flow_step="物理执行与硬件安全",
                    required_evidence=["现场指示灯与硬件排查"],
                )
            )

        elif self.case_type == CaseType.PLC_SIGNAL_ERROR:
            hypos.append(
                Hypothesis(
                    hypothesis_id="H1",
                    description="PLC 硬件端未触发信号或现场接线/传感器松脱",
                    related_flow_step="硬件信号产生",
                    required_evidence=["现场接线与光电指示灯"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H2",
                    description="后端 PLC 通信服务掉线、超时或 Socket 中断",
                    related_flow_step="PLC网络通讯",
                    required_evidence=["PLC通信日志", "端口监听状态"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H3",
                    description="PLC 信号已到达但因业务状态前置校验不满足被后端丢弃",
                    related_flow_step="业务逻辑校验",
                    required_evidence=["后端WARN/INFO业务日志", "主状态表字段"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H4",
                    description="PLC 寄存器地址映射或配置文件配置错误",
                    related_flow_step="配置解析",
                    required_evidence=["生效配置文件", "寄存器映射常量"],
                )
            )

        elif self.case_type == CaseType.CONFIGURATION_ERROR:
            hypos.append(
                Hypothesis(
                    hypothesis_id="H1",
                    description="目标配置项被高优先级配置源覆盖导致修改未生效",
                    related_flow_step="配置优先级加载",
                    required_evidence=["生效配置内容", "多层配置文件比对"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H2",
                    description="外部工控机 ProgramData 独立配置文件未同步更新",
                    related_flow_step="外部环境配置",
                    required_evidence=["外部路径文件检查"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H3",
                    description="配置项拼写错误或参数超出系统合法阈值范围",
                    related_flow_step="参数校验",
                    required_evidence=["启动解析报错日志"],
                )
            )

        elif self.case_type in (CaseType.APPLICATION_ERROR, CaseType.DATA_STATE_ERROR):
            hypos.append(
                Hypothesis(
                    hypothesis_id="H1",
                    description="系统抛出未捕获的运行时异常导致执行中断",
                    related_flow_step="代码逻辑执行",
                    required_evidence=["ERROR日志堆栈"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H2",
                    description="数据库只读/锁表或连接池耗尽导致写状态失败",
                    related_flow_step="数据库持久化",
                    required_evidence=["数据库连接与锁状态", "SQL日志"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H3",
                    description="业务前置状态与当前操作冲突导致状态机拒绝迁移",
                    related_flow_step="状态机流转",
                    required_evidence=["主状态表当前记录", "状态机定义"],
                )
            )

        else:
            hypos.append(
                Hypothesis(
                    hypothesis_id="H1",
                    description="核心服务发生内部未捕获异常或关键逻辑分支失败",
                    related_flow_step="服务内部处理",
                    required_evidence=["应用错误日志"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H2",
                    description="外部系统或硬件未按预期发送确认或网络中断",
                    related_flow_step="外部交互通信",
                    required_evidence=["通信报文与网络连接"],
                )
            )
            hypos.append(
                Hypothesis(
                    hypothesis_id="H3",
                    description="数字事实一切正常，现场可能存在物理设备/带外异常",
                    related_flow_step="物理现场",
                    required_evidence=["现场物理检查清单"],
                )
            )

        return hypos
