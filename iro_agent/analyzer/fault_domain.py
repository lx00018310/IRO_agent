from typing import List, Dict, Any, Optional


ALL_DOMAINS = [
    "Frontend",
    "Backend",
    "Database",
    "Network",
    "Device",
    "Robot",
    "PLC",
    "Android",
    "WRelease",
    "Configuration",
    "Third-party Interface",
    "Unknown",
]


class FaultDomainClassifier:
    """故障域判定器：基于日志错误指纹、交付变更与现场反馈对候选故障域进行概率定级"""

    @classmethod
    def evaluate(
        cls,
        symptom: str,
        recent_release_diff: Optional[Dict[str, Any]] = None,
        error_logs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """评估各个故障域的可能性及凭证"""
        domain_evidence: Dict[str, List[str]] = {d: [] for d in ALL_DOMAINS}
        domain_confidence: Dict[str, str] = {d: "Insufficient evidence" for d in ALL_DOMAINS}

        # 1. 分析 WRelease 变更
        if recent_release_diff and recent_release_diff.get("has_changes"):
            for mod in recent_release_diff.get("changed_modules", []):
                mod_name = mod["module"].lower()
                if "backend" in mod_name:
                    domain_evidence["Backend"].append(f"最新发布包 {recent_release_diff['to_release']} 变更了后端模块")
                    domain_evidence["WRelease"].append(f"后端在最新发布中有代码/打包更新 (SHA变动)")
                if "frontend" in mod_name:
                    domain_evidence["Frontend"].append(f"最新发布包变更了前端静态资源")
                if "face" in mod_name or "device" in mod_name:
                    domain_evidence["Device"].append(f"人脸/硬件对接组件有更新")

        # 2. 分析日志中的特征
        if error_logs:
            for log in error_logs:
                msg = (log.get("message") or "") + " " + (log.get("raw") or "")
                msg_lower = msg.lower()

                if "econnreset" in msg_lower or "websocket send failed" in msg_lower:
                    domain_evidence["Network"].append("发现 WebSocket / TCP 连接重置 (ECONNRESET)")
                    domain_evidence["Frontend"].append("前端通信长连接存在掉线或重连异常")

                if "database" in msg_lower or "timeout" in msg_lower or "connection pool" in msg_lower:
                    domain_evidence["Database"].append(f"日志出现数据库超时或连接池报错: {msg[:60]}")

                if "modbus" in msg_lower or "plc" in msg_lower:
                    domain_evidence["PLC"].append("发现 PLC / Modbus 协议通信异常")

                if "robot" in msg_lower or "dispatch" in msg_lower:
                    domain_evidence["Robot"].append("调度或机器人通信链路异常")

        # 3. 综合评级
        for domain, ev_list in domain_evidence.items():
            if not ev_list:
                domain_confidence[domain] = "Mostly ruled out"
            elif len(ev_list) >= 2:
                domain_confidence[domain] = "High"
            else:
                domain_confidence[domain] = "Medium"

        # 组装返回结果
        return {
            d: {
                "confidence": domain_confidence[d],
                "evidence": domain_evidence[d],
            }
            for d in ALL_DOMAINS
            if domain_confidence[d] != "Mostly ruled out" or d in ("Backend", "Frontend", "Database", "PLC")
        }
