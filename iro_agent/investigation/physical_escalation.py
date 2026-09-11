from typing import List, Optional, Tuple, Any
from iro_agent.investigation.models import CaseType


class PhysicalEscalation:
    """现场硬件与物理带外排查升级器 (Physical Escalation)"""

    @classmethod
    def generate_checklist(cls, case_type: CaseType, symptom: str) -> List[str]:
        """当数字事实无异常或耗尽时，严禁脑补软件bug，生成结合现场工控设备的物理排查清单"""
        checklist: List[str] = []

        if case_type in (CaseType.PLC_SIGNAL_ERROR, CaseType.ROBOT_EXECUTION_ERROR):
            checklist.append("1. 【急停回路与安全门禁】：检查现场物理急停按钮 (E-stop) 是否被拍下，安全光栅/防护门是否被触发断开。")
            checklist.append("2. 【传感器与光电开关】：实地查看对射光电、接近开关指示灯是否点亮，透镜表面是否存在灰尘或物料物理遮挡。")
            checklist.append("3. 【通信接线与供电】：检查工控机至 PLC/交换机网线水晶头是否松动，24V 工业供电电源模块输出电压是否正常。")
            checklist.append("4. 【机械干涉与轮组驱动】：检查轨道或台面是否存在碎屑异物卡阻，机器人驱动电机是否触发热过载或刹车抱死。")
            checklist.append("5. 【现场面板与本地报警】：前往机器人本体或电控箱查看液晶屏物理报警代码，确认是否处于‘手动/示教’维护模式。")

        elif case_type == CaseType.NETWORK_ENVIRONMENT_ERROR:
            checklist.append("1. 【交换机与物理链路】：查看现场工业交换机对应端口 Link/Act 绿灯是否常亮或闪烁。")
            checklist.append("2. 【供电与浪涌保护】：排查现场配电柜防雷浪涌开关与隔离变压器接地是否正常。")
            checklist.append("3. 【网络物理隔离】：排查局域网是否存在未经审批的临时网线跳接导致二层环路或IP冲突。")

        else:
            checklist.append("1. 【工控机电源与硬件环境】：确认工控机主机运行风扇正常、无高温过热告警、电源输入稳定。")
            checklist.append("2. 【外设物理通信线】：核实 USB 加密狗、串口线 (RS485/RS232) 及现场总线终端电阻连接完好。")
            checklist.append("3. 【人工操作排查】：确认是否有操作人员在现场控制柜进行了手动急停或离线模式切换。")

        return checklist

    @classmethod
    def should_escalate(cls, state: Any, hypo_mgr: Any) -> Tuple[bool, str]:
        """
        严格评估是否可以升级至现场物理排查：
        严禁自动将‘数字证据未找到’或‘工具执行超时/失败’推断为‘高度怀疑物理故障’！
        仅当数字证据已充分覆盖且所有数字指标均处于健康状态时，才允许升级。
        """
        # 1. 如果存在工具失败或错误，属于观测断链 (Observability Gap)，不得归咎于物理层
        if getattr(state, "has_tool_failure", lambda: False)():
            return False, "关键排查工具出现异常或超时，属于观测断链 (Observability Gap)，无法确认物理故障"

        # 2. 如果数字排查步数过少，不能草率结案为物理故障
        executed_steps = getattr(state, "executed_steps", [])
        if len(executed_steps) < 2:
            return False, "数字要素排查尚不充分，未覆盖核心日志与业务状态机"

        # 3. 如果已有某个数字假设获得了明确支持，无需升级
        if getattr(hypo_mgr, "has_confirmed_hypothesis", lambda: False)():
            return False, "已存在确凿的数字/软件事实根因，无需升级物理排查"

        if getattr(hypo_mgr, "has_strongly_supported_hypothesis", lambda: False)():
            return False, "软件业务链路或接口已获得强证据支持锁定，无需升级物理排查"

        # 4. 检查是否至少覆盖了日志和核心状态
        evidence_types = [s.evidence_type for s in executed_steps if hasattr(s, "evidence_type")]
        has_log = any("log" in et.lower() for et in evidence_types)
        has_state_or_ver = any("task" in et.lower() or "status" in et.lower() or "version" in et.lower() or "cfg" in et.lower() for et in evidence_types)
        if not (has_log and has_state_or_ver):
            return False, "核心运行日志与业务状态机未完整取证"

        return True, "关键数字证据均已完整覆盖且无异常，建议升级现场物理带外排查"

