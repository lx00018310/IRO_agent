from iro_agent.investigation.models import CaseType
from iro_agent.investigation.physical_escalation import PhysicalEscalation


def test_physical_escalation_checklist_generation():
    """验证数字证据不足时生成专业工控硬件排查 Checklist，杜绝胡乱捏造软件原因"""
    for c_type in [CaseType.PLC_SIGNAL_ERROR, CaseType.ROBOT_EXECUTION_ERROR, CaseType.NETWORK_ENVIRONMENT_ERROR]:
        checklist = PhysicalEscalation.generate_checklist(c_type, symptom="现场设备无动作")
        assert len(checklist) >= 3
        joined = " ".join(checklist)
        assert any(term in joined for term in ("急停", "光电", "接线", "机械", "交换机", "电源"))
