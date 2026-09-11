import json
from pathlib import Path
from typing import List
from iro_agent.evaluation.models import EvalRunSummary, CaseEvalResult, EvalStatus


class EvalReporter:
    """评测结果汇总与报告生成器"""

    @classmethod
    def generate_markdown_report(cls, summary: EvalRunSummary) -> str:
        lines = []
        lines.append(f"# IRO_agent 故障诊断评测报告 (Run: {summary.run_id})")
        lines.append("")
        lines.append(f"- **数据集体系**: `{summary.dataset_type.upper()}`")
        lines.append(f"- **用例总数**: {summary.total_cases}")
        lines.append(f"- **通过用例 (Pass)**: {summary.passed_cases}")
        lines.append(f"- **失败用例 (Fail)**: {summary.failed_cases}")
        lines.append(f"- **错误/异常 (Error)**: {summary.error_cases}")
        lines.append(f"- **平均综合得分**: {summary.average_score * 100:.2f}%")
        lines.append(f"- **安全红线违规数**: {summary.safety_violations}")
        lines.append("")
        lines.append("## 用例明细清单")
        lines.append("")
        lines.append("| Case ID | 状态 | 综合得分 | 根因评分 | 证据链 | 路径质量 | 安全合规 | 终止原因 |")
        lines.append("|---|---|---|---|---|---|---|---|")

        for r in summary.results:
            lines.append(
                f"| `{r.case_id}` | **{r.status.value}** | {r.final_score * 100:.1f}% | "
                f"{r.root_cause_score * 100:.1f}% | {r.evidence_score * 100:.1f}% | "
                f"{r.path_score * 100:.1f}% | {r.safety_score * 100:.1f}% | {r.stop_reason[:30]} |"
            )

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def save_run_reports(cls, run_dir: Path, summary: EvalRunSummary) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        # 1. 保存 summary.json
        summary_file = run_dir / "summary.json"
        summary_file.write_text(json.dumps(summary.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. 保存 report.md
        md_content = cls.generate_markdown_report(summary)
        report_file = run_dir / "report.md"
        report_file.write_text(md_content, encoding="utf-8")
