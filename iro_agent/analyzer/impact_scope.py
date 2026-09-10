from typing import Dict, Any, List, Optional


class ImpactScopeEvaluator:
    """
    影响面与严重程度评估器：判定业务功能受损范围并评定 P0~P3 级别。
    核心完整性准则：
    1. 所有业务功能状态默认必须初始化为 'Unknown'。
    2. 严禁无凭证默认标记为 'Normal' (正常)。
    3. 仅当存在明确凭证证实功能无损时，方可标为 'Normal'。
    4. 存在故障特征受损事实时，标为 'Affected'。
    """

    DEFAULT_FUNCTIONS = [
        "新订单创建/接收",
        "自动装车/上车调度",
        "PLC 信号互锁与到位检测",
        "前端看板监控与刷新",
        "历史数据与发货清单查询",
    ]

    @classmethod
    def evaluate(
        cls,
        symptom: str,
        fault_domains: Optional[Dict[str, Any]] = None,
        affected_keywords: Optional[List[str]] = None,
        confirmed_normal_functions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        P0: 产线/整线停机或系统完全不可用
        P1: 核心业务中断 (如订单生成/上车流程停滞)
        P2: 局部功能受损，主流程仍可运转
        P3: 轻微异常或非阻断性提示
        """
        symptom_lower = (symptom or "").lower()

        # 核心完整性修复：所有功能初始状态一律设为 Unknown，绝不预设 Normal！
        functions_status: Dict[str, str] = {fn: "Unknown" for fn in cls.DEFAULT_FUNCTIONS}

        # 若存在已确认正常的凭据，标记为 Normal
        if confirmed_normal_functions:
            for fn in confirmed_normal_functions:
                if fn in functions_status:
                    functions_status[fn] = "Normal"

        severity = "P2"
        severity_reason = "部分功能可能受损，现场状态持续评估中。"

        # 根据确凿证据与症状判定受影响项 (Affected)
        if any(kw in symptom_lower for kw in ["卡死", "卡住", "中断", "无法装车", "停线", "崩溃", "全部失败", "拒收", "物料拒收"]):
            functions_status["自动装车/上车调度"] = "Affected (调度流程受阻/物料拒收)"
            functions_status["新订单创建/接收"] = "Affected (可能连带受阻)"
            severity = "P1"
            severity_reason = "核心上车作业或装车调度流程受阻，直接影响现场生产节拍。"

        if any(kw in symptom_lower for kw in ["整线停产", "全停", "主服务挂了"]):
            for k in functions_status:
                functions_status[k] = "Affected (整系统不可用)"
            severity = "P0"
            severity_reason = "整系统不可用或产线完全停摆。"

        if any(kw in symptom_lower for kw in ["掉线", "websocket", "刷新慢", "界面提示", "弹窗", "显示屏"]):
            functions_status["前端看板监控与刷新"] = "Affected (长连接偶发断开/刷新延迟)"
            if severity not in ("P0", "P1"):
                severity = "P2"
                severity_reason = "工位监控看板展示异常，主干数据调度仍在运行。"

        return {
            "severity": severity,
            "severity_reason": severity_reason,
            "functions_status": functions_status,
        }
