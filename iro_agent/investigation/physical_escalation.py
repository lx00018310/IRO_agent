from typing import List, Optional
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
