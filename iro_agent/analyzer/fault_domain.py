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
    """
    故障域判定器：基于真实证据对候选故障域进行评定。
    核心规则：
    1. 缺乏证据 != 已排除 (No evidence != Mostly ruled out)。
    2. 无证据的故障域必须评定为 'Insufficient evidence'。
    3. 仅当存在明确否定证据时，才评定为 'Mostly ruled out'。
    4. 存在正向凭证时，评定为 High / Medium / Low。
    """

    @classmethod
    def evaluate(
        cls,
        symptom: str,
        recent_release_diff: Optional[Dict[str, Any]] = None,
        error_logs: Optional[List[Dict[str, Any]]] = None,
        ruled_out_domains: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """评估各个故障域的可能性及凭证"""
        domain_evidence: Dict[str, List[str]] = {d: [] for d in ALL_DOMAINS}
        domain_confidence: Dict[str, str] = {d: "Insufficient evidence" for d in ALL_DOMAINS}
        explicit_ruled_out = set(ruled_out_domains or [])

        # 1. 分析版本发布变动（WRelease / Git）
        if recent_release_diff and recent_release_diff.get("has_changes"):
            for mod in recent_release_diff.get("changed_modules", []):
                mod_name = str(mod.get("module", "")).lower()
                to_rel = recent_release_diff.get("to_release", "最新发布")
                if "backend" in mod_name:
                    domain_evidence["Backend"].append(f"最新发布 {to_rel} 包含后端模块变更")
                    domain_evidence["WRelease"].append(f"后端在最新发布中有代码/打包更新 (SHA变动)")
                if "frontend" in mod_name:
                    domain_evidence["Frontend"].append(f"最新发布 {to_rel} 变更了前端静态资源")
                if "face" in mod_name or "device" in mod_name:
                    domain_evidence["Device"].append(f"硬件/人脸对接组件有发布更新")

        # 2. 分析日志特征
        if error_logs:
            for log in error_logs:
                msg = (log.get("message") or "") + " " + (log.get("raw") or "")
                msg_lower = msg.lower()

                if "econnreset" in msg_lower or "websocket send failed" in msg_lower or "connection refused" in msg_lower:
                    domain_evidence["Network"].append("捕获到网络连接重置或中断 (ECONNRESET/Refused)")
                    domain_evidence["Frontend"].append("前端通信长连接存在断开或刷新异常")

                if "database" in msg_lower or "timeout" in msg_lower or "connection pool" in msg_lower or "deadlock" in msg_lower:
                    domain_evidence["Database"].append(f"日志出现数据库超时、死锁或连接池报错: {msg[:60]}")

                if "modbus" in msg_lower or "plc" in msg_lower:
                    domain_evidence["PLC"].append("日志出现 PLC / Modbus 通信故障")

                if "robot" in msg_lower or "dispatch" in msg_lower:
                    domain_evidence["Robot"].append("调度或机器人通信链路异常")

        # 3. 分析故障现象关键词
        symptom_lower = symptom.lower() if symptom else ""
        if any(kw in symptom_lower for kw in ["拒收", "物料", "上车", "装车", "卡死", "阻塞"]):
            domain_evidence["Backend"].append("业务阻塞发生在装车/调度业务逻辑处理流程中")

        # 4. 综合评级：严格遵循证据完整性规则
        for domain in ALL_DOMAINS:
            ev_list = domain_evidence[domain]
            if domain in explicit_ruled_out:
                domain_confidence[domain] = "Mostly ruled out"
            elif ev_list:
                if len(ev_list) >= 2:
                    domain_confidence[domain] = "High"
                else:
                    domain_confidence[domain] = "Medium"
            else:
                # 核心修正：缺乏证据必须评定为 Insufficient evidence，严禁判定为 Mostly ruled out！
                domain_confidence[domain] = "Insufficient evidence"

        return {
            d: {
                "confidence": domain_confidence[d],
                "evidence": domain_evidence[d],
            }
            for d in ALL_DOMAINS
        }
