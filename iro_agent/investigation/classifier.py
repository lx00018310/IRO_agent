from typing import List, Optional
from iro_agent.investigation.models import CaseType


class InvestigationCaseClassifier:
    """现场故障多标签案例分类器 (Case Classifier)"""

    @classmethod
    def classify(cls, symptom: str, error_logs: Optional[List[str]] = None) -> CaseType:
        s = (symptom or "").lower()
        logs_str = " ".join(error_logs or []).lower()
        text = f"{s} {logs_str}"

        # 1. PLC 信号类异常
        if any(k in text for k in ("plc", "p2c", "c2p", "光电", "寄存器", "开门信号", "到位信号", "感应")):
            return CaseType.PLC_SIGNAL_ERROR

        # 2. 机器人 / AGV 执行类异常
        if any(k in text for k in ("机器人不走", "机器人不动", "agv", "小车", "堆垛机", "送餐", "上车", "不走", "停滞")):
            return CaseType.ROBOT_EXECUTION_ERROR

        # 3. 版本更新相关异常
        if any(k in text for k in ("发版", "更新后", "升级后", "上线后", "commit", "版本变更", "最新包")):
            return CaseType.VERSION_CHANGE_ERROR

        # 4. 配置类异常
        if any(k in text for k in ("配置", "端口", "超时时间", "轮询间隔", "config", "settings", "ip地址", "修改参数")):
            return CaseType.CONFIGURATION_ERROR

        # 5. 接口与回调通信异常
        if any(k in text for k in ("回调", "callback", "receipt", "ack", "webhook", "未收到回执", "接口超时")):
            return CaseType.INTERFACE_COMMUNICATION_ERROR

        # 6. 数据与状态一致性异常
        if any(k in text for k in ("状态不对", "卡在", "未更新", "状态卡死", "数据不一致", "未变更为")):
            return CaseType.DATA_STATE_ERROR

        # 7. 网络与系统环境异常
        if any(k in text for k in ("掉线", "网络断开", "连接被拒绝", "connection refused", "timeout", "无法连接", "port")):
            return CaseType.NETWORK_ENVIRONMENT_ERROR

        # 8. 应用 / 后端报错
        if any(k in text for k in ("exception", "nullpointer", "error", "500", "崩溃", "内存溢出", "oom", "报错")):
            return CaseType.APPLICATION_ERROR

        return CaseType.UNKNOWN_RUNTIME_FAULT
