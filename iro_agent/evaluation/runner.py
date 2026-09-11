import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from iro_agent.evaluation.models import (
    EvalCase,
    CaseEvalResult,
    EvalRunSummary,
    EvalStatus,
)
from iro_agent.evaluation.dataset import EvalDatasetLoader
from iro_agent.evaluation.scoring import EvaluationScorer
from iro_agent.evaluation.trajectory import TrajectoryWriter
from iro_agent.evaluation.reporter import EvalReporter
from iro_agent.investigation.harness import InvestigationHarness


class EvaluationRunner:
    """自动化基准评测运行器 (Evaluation Runner)"""

    def __init__(
        self,
        dataset_type: str = "dev",
        custom_path: Optional[str] = None,
        tool_handlers: Optional[Dict[str, Any]] = None,
        output_dir: str = ".eval_runs",
    ):
        self.dataset_type = dataset_type
        self.custom_path = custom_path
        self.tool_handlers = tool_handlers
        self.output_dir = Path(output_dir)

    def run(
        self,
        category: Optional[str] = None,
        case_id: Optional[str] = None,
        repeat: int = 1,
        verbose: bool = False,
    ) -> EvalRunSummary:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # 1. 加载评测集
        cases = EvalDatasetLoader.resolve_dataset(
            dataset_type=self.dataset_type,
            custom_path=self.custom_path,
            category=category,
            case_id=case_id,
        )

        results: List[CaseEvalResult] = []
        safety_violations = 0

        for case in cases:
            for rep in range(repeat):
                symptom = case.input.get("symptom", "")
                t_start = time.time()

                try:
                    # 生产 Agent Context 与评测用例期望完全隔离，Agent 严禁感知 Ground Truth
                    harness = InvestigationHarness(tool_handlers=self.tool_handlers)
                    report = harness.investigate(symptom=symptom, verbose=verbose)
                    elapsed_ms = int((time.time() - t_start) * 1000)

                    eval_res = EvaluationScorer.score_case(case, report, duration_ms=elapsed_ms)
                except Exception as exc:
                    elapsed_ms = int((time.time() - t_start) * 1000)
                    # 评测模式下严禁静默 fallback，发生执行中断必须如实标记为 INFRA_ERROR
                    eval_res = CaseEvalResult(
                        case_id=case.case_id,
                        status=EvalStatus.INFRA_ERROR,
                        final_score=0.0,
                        duration_ms=elapsed_ms,
                        stop_reason=f"执行异常崩溃: {str(exc)}",
                        final_answer="",
                    )

                if eval_res.safety_score == 0.0:
                    safety_violations += 1

                # 2. 归档单 Case 轨迹文件
                traj_file = TrajectoryWriter.save_case_trajectory(
                    run_dir=run_dir,
                    case_id=case.case_id if repeat == 1 else f"{case.case_id}_rep{rep+1}",
                    eval_result=eval_res,
                )
                eval_res.trajectory_path = str(traj_file)
                results.append(eval_res)

        # 3. 统计汇总
        total = len(results)
        passed = sum(1 for r in results if r.status == EvalStatus.PASS)
        failed = sum(1 for r in results if r.status == EvalStatus.FAIL)
        errors = sum(1 for r in results if r.status in (EvalStatus.ERROR, EvalStatus.INFRA_ERROR))
        avg_score = round(sum(r.final_score for r in results) / total, 3) if total > 0 else 0.0

        summary = EvalRunSummary(
            run_id=run_id,
            dataset_type=self.dataset_type,
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            error_cases=errors,
            average_score=avg_score,
            safety_violations=safety_violations,
            results=results,
        )

        # 4. 保存报告
        EvalReporter.save_run_reports(run_dir, summary)
        return summary
