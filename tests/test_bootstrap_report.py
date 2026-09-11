from iro_agent.knowledge.models import (
    ProjectBlueprint,
    ProjectMetadata,
    ModuleKnowledge,
    BusinessFlow,
    TableKnowledge,
)
from iro_agent.knowledge.bootstrap_report import BootstrapReportGenerator


def test_bootstrap_report_generation():
    """验证 BootstrapReportGenerator 生成完备的 Markdown 报告"""
    meta = ProjectMetadata(
        project_id="TASK-013",
        project_name="武汉自动上车显示屏",
        generated_at="2026-09-11 10:00:00",
        source_root="/mock/path",
    )
    bp = ProjectBlueprint(
        project=meta,
        modules=[
            ModuleKnowledge(
                module_id="backend",
                name="backend",
                business_role="后端核心控制服务",
                confidence="CONFIRMED",
            )
        ],
        business_flows=[
            BusinessFlow(
                flow_id="dock_dispatch",
                name="月台调度流程",
                aliases=["叫料", "调度"],
                steps=["请求月台", "下发任务", "回执"],
                controller="DockController",
                source_of_truth="dock_task.status",
            )
        ],
        database_tables=[
            TableKnowledge(
                table_name="dock_task",
                business_role="月台任务表",
                table_type="current_state",
                not_for=["历史报文对账"],
            )
        ],
        critic_report={
            "confirmed_facts": ["月台任务表为核心主状态源"],
            "strongly_inferred_facts": ["调度心跳有效"],
            "weak_inferences": [],
            "unknown_areas": ["光电传感器信号接线"],
            "contradictions": [],
        },
        bootstrap_stats={
            "glm_calls": 7,
            "files_deep_read": 12,
            "lines_inspected": 2450,
            "elapsed_seconds": 18.5,
        },
        known_unknowns=["光电传感器信号接线"],
    )

    report = BootstrapReportGenerator.generate(bp)
    assert "# IRO_agent 深度项目自举认知报告" in report
    assert "真实 GLM 模型调用轮次**: `7` 次" in report
    assert "源码深入精读文件数**: `12` 个" in report
    assert "backend" in report
    assert "月台调度流程" in report
    assert "光电传感器信号接线" in report
    assert "dock_task" in report
