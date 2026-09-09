from typing import Dict, Any, List


class ImpactScopeEvaluator:
    """影响面与严重程度评估器：判定业务功能受损范围并评定 P0~P3 级别"""

    @classmethod
    def evaluate(cls, symptom: str, fault_domains: Dict[str, Any], affected_keywords: List[str]) -> Dict[str, Any]:
        """
        P0: 产线/整线停机或系统完全不可用
        P1: 核心业务中断 (如订单生成/上车流程停滞)
        P2: 局部功能受损，主流程仍可运转
        P3: 轻微异常或非阻断性提示
        """
        symptom_lower = symptom.lower()

        # 业务功能影响推断
        functions_status = {
            "新订单创建/接收": "正常",
            "自动装车/上车调度": "正常",
            "PLC 信号互锁与到位检测": "正常",
            "前端看板监控与刷新": "正常",
            "历史数据与发货清单查询": "正常",
        }

        severity = "P2"
        severity_reason = "部分功能出现异常，正在持续评估影响范围。"

        if any(kw in symptom_lower for kw in ["卡死", "中断", "无法装车", "停线", "崩溃", "全部失败"]):
            functions_status["自动装车/上车调度"] = "受影响 (核心流程阻塞)"
            functions_status["新订单创建/接收"] = "可能受阻"
            severity = "P1"
            severity_reason = "核心上车作业流程受阻，可能影响现场发运节拍。"

        if any(kw in symptom_lower for kw in ["整线停产", "全停", "主服务挂了"]):
            for k in functions_status:
                functions_status[k] = "完全不可用"
            severity = "P0"
            severity_reason = "整系统不可用或产线完全停摆。"

        if any(kw in symptom_lower for kw in ["掉线", "websocket", "刷新慢", "界面提示", "弹窗"]):
            functions_status["前端看板监控与刷新"] = "受影响 (长连接偶发断开/重连)"
            if severity not in ("P0", "P1"):
                severity = "P2"
                severity_reason = "监控看板展示或局部交互偶发异常，后台作业逻辑仍在运转。"

        return {
            "severity": severity,
            "severity_reason": severity_reason,
            "functions_status": functions_status,
        }
