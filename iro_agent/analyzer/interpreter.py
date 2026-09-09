from typing import Dict, Any, List, Optional


class BusinessLanguageInterpreter:
    """业务语言转译器：极简输出核心诊断结论、关键事实依据与排查建议，去除所有冗余模板套话"""

    @classmethod
    def render_report(
        cls,
        conclusion: str,
        impact_scope: Optional[Dict[str, Any]] = None,
        evidence_list: Optional[List[str]] = None,
        similar_stats: Optional[Dict[str, Any]] = None,
        recommended_checks: Optional[List[str]] = None,
        confidence: str = "High",
        timeline_markdown: Optional[str] = None,
    ) -> str:
        """组装极度精简的自然语言诊断文本"""
        parts = [f"**核心结论**：{conclusion.strip()}"]

        if evidence_list:
            clean_evs = [ev.strip() for ev in evidence_list if ev.strip()]
            if clean_evs:
                ev_lines = "\n".join([f"- {ev}" for ev in clean_evs[:3]])
                parts.append(f"**关键依据**：\n{ev_lines}")

        if recommended_checks:
            clean_chks = [c.strip() for c in recommended_checks if c.strip()]
            if clean_chks:
                chk_lines = "\n".join([f"- {c}" for c in clean_chks[:2]])
                parts.append(f"**排查建议**：\n{chk_lines}")

        return "\n\n".join(parts)
