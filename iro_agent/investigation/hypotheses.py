from typing import List, Dict, Any, Optional
from iro_agent.investigation.models import CaseType, Hypothesis, HypothesisStatus


class HypothesisManager:
    """竞争性假设管理器 (Hypothesis Manager: 2~6 个候选假设生命周期)"""

    def __init__(self, case_type: CaseType, symptom: str, flows: Optional[List[Any]] = None):
        self.case_type = case_type
        self.symptom = symptom
        self.flows = flows or []
        self.hypotheses: List[Hypothesis] = self._generate_initial_hypotheses()

    def _generate_initial_hypotheses(self) -> List[Hypothesis]:
        """依据故障类别与业务流链条生成初始竞争性假设 (2~6个)"""
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
    ) -> None:
        h = self.get_hypothesis(hypothesis_id)
        if not h:
            return

        h.status = new_status
        if new_status in (HypothesisStatus.CONFIRMED, HypothesisStatus.STRONGLY_SUPPORTED, HypothesisStatus.SUPPORTED):
            if evidence and evidence not in h.supporting_evidence:
                h.supporting_evidence.append(evidence)
            h.confidence = "High" if new_status == HypothesisStatus.CONFIRMED else "Medium"
        elif new_status == HypothesisStatus.RULED_OUT:
            if evidence and evidence not in h.contradicting_evidence:
                h.contradicting_evidence.append(evidence)
            h.confidence = "RuledOut"

    def rule_out(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> None:
        self.update_status(hypothesis_id, HypothesisStatus.RULED_OUT, reason, evidence)

    def confirm(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> None:
        self.update_status(hypothesis_id, HypothesisStatus.CONFIRMED, reason, evidence)

    def strongly_support(self, hypothesis_id: str, reason: str, evidence: Optional[str] = None) -> None:
        self.update_status(hypothesis_id, HypothesisStatus.STRONGLY_SUPPORTED, reason, evidence)

    def get_top_hypothesis(self) -> Optional[Hypothesis]:
        # 优先级：CONFIRMED > STRONGLY_SUPPORTED > SUPPORTED > UNRESOLVED
        order = {
            HypothesisStatus.CONFIRMED: 10,
            HypothesisStatus.STRONGLY_SUPPORTED: 8,
            HypothesisStatus.SUPPORTED: 5,
            HypothesisStatus.UNRESOLVED: 2,
            HypothesisStatus.WEAK: 1,
            HypothesisStatus.RULED_OUT: 0,
        }
        active = [h for h in self.hypotheses if h.status != HypothesisStatus.RULED_OUT]
        if not active:
            return None
        return max(active, key=lambda h: (order.get(h.status, 0), len(h.supporting_evidence)))

    def has_confirmed_hypothesis(self) -> bool:
        return any(h.status == HypothesisStatus.CONFIRMED for h in self.hypotheses)

    def has_strongly_supported_hypothesis(self) -> bool:
        return any(h.status == HypothesisStatus.STRONGLY_SUPPORTED for h in self.hypotheses)
