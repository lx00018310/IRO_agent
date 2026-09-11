import json
from pathlib import Path
from typing import List, Optional, Union
from iro_agent.evaluation.models import EvalCase

try:
    import yaml
except ImportError:
    yaml = None


class EvalDatasetLoader:
    """评测数据集加载与管理器 (Eval Dataset Loader)"""

    @classmethod
    def load_case_from_file(cls, file_path: Union[str, Path]) -> EvalCase:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Eval case file not found: {path}")

        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            if yaml is None:
                raise ImportError("读取 YAML 格式用例需要安装 PyYAML：pip install pyyaml")
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)

        return EvalCase(**data)

    @classmethod
    def load_cases_from_dir(
        cls,
        dir_path: Union[str, Path],
        category: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> List[EvalCase]:
        root = Path(dir_path)
        if not root.exists():
            return []

        cases: List[EvalCase] = []
        # 递归遍历 json 与 yaml 用例
        for file in sorted(root.rglob("*")):
            if file.is_file() and file.suffix.lower() in (".json", ".yaml", ".yml"):
                try:
                    case = cls.load_case_from_file(file)
                    if case_id and case.case_id != case_id:
                        continue
                    if category and case.category.lower() != category.lower():
                        continue
                    cases.append(case)
                except Exception:
                    # 忽略非 EvalCase 格式的辅助数据文件
                    continue

        return cases

    @classmethod
    def resolve_dataset(
        cls,
        dataset_type: str,
        custom_path: Optional[str] = None,
        category: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> List[EvalCase]:
        """按 DEV / REGRESSION / EXTERNAL 体系解析用例"""
        if dataset_type == "external":
            if not custom_path:
                raise ValueError("External dataset requires --dataset path specified.")
            target_dir = Path(custom_path)
        elif dataset_type == "dev":
            target_dir = Path("evaluation_cases/dev")
        elif dataset_type == "regression":
            target_dir = Path("evaluation_cases/regression")
        else:
            raise ValueError(f"Unknown dataset type: {dataset_type}")

        return cls.load_cases_from_dir(target_dir, category=category, case_id=case_id)
