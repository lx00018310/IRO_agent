from typing import Dict, Any, List, Optional


class BusinessLanguageInterpreter:
    """业务语言转译器：将代码、SQL、堆栈等底层技术证据转译为现场调度与管理人员可直接理解的诊断报告"""

    @classmethod
    def render_report(
        cls,
        conclusion: str,
        impact_scope: Dict[str, Any],
        evidence_list: List[str],
        similar_stats: Optional[Dict[str, Any]] = None,
        recommended_checks: Optional[List[str]] = None,
        confidence: str = "High",
        timeline_markdown: Optional[str] = None,
    ) -> str:
        """组装符合工业现场标准交付规范的自然语言诊断文本"""
        sections = []

        # 1. 结论
        sections.append(f"### 1. 诊断结论\n{conclusion}")

        # 2. 业务影响范围
        sev = impact_scope.get("severity", "P2")
        reason = impact_scope.get("severity_reason", "")
        fstatus = impact_scope.get("functions_status", {})
        func_lines = "\n".join([f"- **{k}**：{v}" for k, v in fstatus.items()])
        sections.append(
            f"### 2. 业务影响分析 (级别: {sev})\n"
            f"**定级说明**：{reason}\n\n"
            f"**具体功能状态**：\n{func_lines}"
        )

        # 3. 支撑证据
        if evidence_list:
            ev_text = "\n".join([f"{idx}. {ev}" for idx, ev in enumerate(evidence_list, start=1)])
            sections.append(f"### 3. 关键事实与研判证据\n{ev_text}")

        # 4. 时间线 (可选)
        if timeline_markdown:
            sections.append(f"### 4. 事件脉络时间线\n{timeline_markdown}")

        # 5. 历史相似案例
        if similar_stats and similar_stats.get("total_similar_count", 0) > 0:
            count = similar_stats["total_similar_count"]
            period = similar_stats.get("period_days", 90)
            latest = similar_stats.get("latest_incident_date", "")
            domain_breakdown = ", ".join([f"{k}: {v}起" for k, v in similar_stats.get("domain_breakdown", {}).items()])
            sections.append(
                f"### 5. 历史相似案例统计\n"
                f"- 过去 {period} 天内共匹配到 **{count}** 起相似现象记录。\n"
                f"- 故障归因分布：{domain_breakdown}\n"
                f"- 最近一次相似案例发生于：{latest}"
            )
        else:
            sections.append("### 5. 历史相似案例统计\n近期未记录到完全一致的相同故障案例。")

        # 6. 建议排查措施
        checks = recommended_checks or [
            "核对工控机当前运行版本是否与今天下发的 WRelease 交付包一致；",
            "检查工控机与前端工位显示屏之间的局域网交换机及网线连接；",
            "若核心装车调度正常，暂无需重启后端主服务，保持观察。",
        ]
        chk_text = "\n".join([f"{i}. {c}" for i, c in enumerate(checks, start=1)])
        sections.append(f"### 6. 建议现场排查步骤\n{chk_text}")

        # 7. 置信度
        sections.append(f"### 7. 诊断置信度\n**{confidence}**")

        return "\n\n".join(sections)
