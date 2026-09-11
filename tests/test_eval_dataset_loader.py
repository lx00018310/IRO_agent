import pytest
import json
from pathlib import Path
from iro_agent.evaluation.models import EvalCase
from iro_agent.evaluation.dataset import EvalDatasetLoader


def test_load_eval_case_from_json(tmp_path):
    case_data = {
        "case_id": "test_case_001",
        "case_version": 1,
        "category": "plc",
        "severity": "high",
        "input": {"symptom": "PLC通讯中断"},
        "expectation": {
            "acceptable_root_causes": ["plc_link_down"],
            "required_evidence_types": ["plc_log"],
            "forbidden_claims": ["电机烧毁"],
            "forbidden_actions": ["db_write"],
        },
    }
    f = tmp_path / "case_001.json"
    f.write_text(json.dumps(case_data), encoding="utf-8")

    loaded = EvalDatasetLoader.load_case_from_file(f)
    assert loaded.case_id == "test_case_001"
    assert loaded.category == "plc"
    assert "plc_link_down" in loaded.expectation.acceptable_root_causes


def test_filter_cases_by_category_and_id(tmp_path):
    c1 = {
        "case_id": "c1",
        "category": "plc",
        "input": {"symptom": "s1"},
    }
    c2 = {
        "case_id": "c2",
        "category": "robot",
        "input": {"symptom": "s2"},
    }
    (tmp_path / "c1.json").write_text(json.dumps(c1), encoding="utf-8")
    (tmp_path / "c2.json").write_text(json.dumps(c2), encoding="utf-8")

    all_cases = EvalDatasetLoader.load_cases_from_dir(tmp_path)
    assert len(all_cases) == 2

    plc_only = EvalDatasetLoader.load_cases_from_dir(tmp_path, category="plc")
    assert len(plc_only) == 1
    assert plc_only[0].case_id == "c1"

    c2_only = EvalDatasetLoader.load_cases_from_dir(tmp_path, case_id="c2")
    assert len(c2_only) == 1
    assert c2_only[0].category == "robot"
