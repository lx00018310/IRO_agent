import json
from pathlib import Path
from typing import Dict, Any, Optional
from iro_agent.evaluation.models import CaseEvalResult


class TrajectoryWriter:
    """评测轨迹归档写入器"""

    @classmethod
    def save_case_trajectory(
        cls,
        run_dir: Path,
        case_id: str,
        eval_result: CaseEvalResult,
        raw_trace: Optional[Dict[str, Any]] = None,
    ) -> Path:
        cases_dir = run_dir / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)

        target_file = cases_dir / f"{case_id}.json"
        data = {
            "eval_result": eval_result.model_dump(),
            "raw_trace": raw_trace or {},
        }

        target_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return target_file
