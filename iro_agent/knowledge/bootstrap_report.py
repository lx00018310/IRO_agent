from typing import Dict, Any, List
from iro_agent.knowledge.models import ProjectBlueprint


class BootstrapReportGenerator:
    """深度项目自举质量与认知报告生成器 (Stage 9: Persist + Bootstrap Report)"""

    @classmethod
    def generate(cls, blueprint: ProjectBlueprint) -> str:
        stats = blueprint.bootstrap_stats or {}
        glm_calls = stats.get("glm_calls", 0)
        files_read = stats.get("files_deep_read", 0)
        lines_inspected = stats.get("lines_inspected", 0)
        elapsed = stats.get("elapsed_seconds", 0.0)

        lines: List[str] = []
        lines.append("# IRO_agent 深度项目自举认知报告 (Deep Bootstrap Report)")
        lines.append("")
        lines.append(f"**目标工程**: `{blueprint.project.project_name}`  ")
        lines.append(f"**自举时间**: `{blueprint.project.generated_at}`  ")
        lines.append(f"**自举耗时**: `{elapsed}s`  ")
        lines.append("")
        lines.append("## 1. 深度学习与提纯工作量")
        lines.append("")
        lines.append(f"- **真实 GLM 模型调用轮次**: `{glm_calls}` 次")
        lines.append(f"- **源码深入精读文件数**: `{files_read}` 个")
        lines.append(f"- **核心源码阅读行数**: `{lines_inspected}` 行")
        lines.append("")

        lines.append("## 2. 模块职责与置信度")
        lines.append("")
        lines.append("| 模块标识 | 模块名称 | 现场业务角色 | 置信度等级 |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for m in blueprint.modules:
            lines.append(f"| `{m.module_id}` | {m.name} | {m.business_role[:40]} | **{m.confidence}** |")
        lines.append("")

        lines.append("## 3. 端到端核心业务流提炼")
        lines.append("")
        for f in blueprint.business_flows:
            lines.append(f"### 流程: {f.name} ({f.flow_id or 'flow'})")
            lines.append(f"- **别名/工控现场说法**: {', '.join(f.aliases) or '无'}")
            lines.append(f"- **核心步骤**: {', '.join(f.steps) if f.steps else '单链路调度'}")
            lines.append(f"- **责任类/控制器**: `{f.controller}` | 服务: `{', '.join(f.services[:3])}`")
            lines.append(f"- **权威数据源 (Source of Truth)**: `{f.source_of_truth or '见状态主表'}`")
            lines.append(f"- **关联外部硬件/系统**: {', '.join(f.external_systems) or '系统内部'}")
            if f.unknown_steps:
                lines.append(f"- **未知/暗区步骤**: {', '.join(f.unknown_steps)}")
            lines.append("")

        lines.append("## 4. 关键数据表语义与角色划分")
        lines.append("")
        lines.append("| 数据表名 | 表类型分类 | 核心业务职责 | 严禁排查误区 (Not For) |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for t in blueprint.database_tables:
            not_for_desc = ", ".join(t.not_for) if t.not_for else "无"
            lines.append(f"| `{t.table_name}` | `{t.table_type}` | {t.business_role[:30]} | {not_for_desc} |")
        lines.append("")

        lines.append("## 5. 批评审查通道审计结果 (Critic Pass)")
        lines.append("")
        critic = blueprint.critic_report or {}
        confirmed = critic.get("confirmed_facts", [])
        strongly = critic.get("strongly_inferred_facts", [])
        weak = critic.get("weak_inferences", [])
        contradictions = critic.get("contradictions", [])

        lines.append(f"- **确凿事实项**: {len(confirmed)} 项")
        for c in confirmed[:5]:
            lines.append(f"  - [Confirmed] {c}")
        lines.append(f"- **强推论事实项**: {len(strongly)} 项")
        for s in strongly[:5]:
            lines.append(f"  - [Strongly Inferred] {s}")
        if weak:
            lines.append(f"- **存疑推论项**: {len(weak)} 项")
            for w in weak:
                lines.append(f"  - [Warning/Weak] {w}")
        if contradictions:
            lines.append(f"- **逻辑冲突告警**: {len(contradictions)} 项")
            for ct in contradictions:
                lines.append(f"  - [Contradiction] {ct}")
        lines.append("")

        lines.append("## 6. 现场已知未知盲区 (Known Unknowns)")
        lines.append("")
        lines.append("> 工业排查准则：严禁捏造不存在的软件原因，未知区域必须在现场排查时明确标出。")
        lines.append("")
        if blueprint.known_unknowns:
            for uk in blueprint.known_unknowns:
                lines.append(f"- [未知暗区] {uk}")
        else:
            lines.append("- 无显式遗留未知项。")
        lines.append("")

        return "\n".join(lines)
