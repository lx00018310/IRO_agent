import pytest
from iro_agent.investigation.llm_planner import LLMInvestigationPlanner
from iro_agent.investigation.models import (
    Hypothesis,
    HypothesisStatus,
    EvidenceRecord,
    EvidenceTier,
)


def test_planner_prompt_explicitly_contains_evidence_ids_and_hypothesis_ids():
    """验证 LLM Planner 构建的 Prompt 中显式包含 Evidence ID (如 EV_001) 与 Hypothesis ID，支持精准溯源"""
    planner = LLMInvestigationPlanner()

    hypos = [
        Hypothesis(hypothesis_id="H1", description="调度服务通信超时", status=HypothesisStatus.UNRESOLVED),
        Hypothesis(hypothesis_id="H2", description="PLC寄存器状态未就绪", status=HypothesisStatus.UNRESOLVED),
    ]

    evidences = [
        EvidenceRecord(
            evidence_id="EV_001",
            source_type="log",
            source_name="backend.log",
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
            raw_summary="Connection timed out after 3000ms",
            normalized_fact="HTTP 504 Gateway Timeout connecting to PLC adapter",
            reliability=0.95,
        ),
        EvidenceRecord(
            evidence_id="EV_002",
            source_type="database",
            source_name="sys_task",
            tier=EvidenceTier.TIER_1A_RUNTIME_DIGITAL,
            raw_summary="task_status=PENDING",
            normalized_fact="任务 1001 停留在 PENDING 状态未被分发",
            reliability=1.0,
        ),
    ]

    prompt = planner._build_prompt(
        symptom="小车未响应调度指令",
        hypotheses=hypos,
        evidence_records=evidences,
        remaining_budget=5,
    )

    # 1. 核心断言：Prompt 文本中必须显式暴露真实的 Evidence ID，绝不能让模型瞎猜
    assert "EV_001" in prompt
    assert "EV_002" in prompt

    # 2. 核心断言：Prompt 必须显式展示假设 ID
    assert "H1" in prompt
    assert "H2" in prompt

    # 3. 核心断言：Prompt 必须包含严禁编造 Evidence ID 的安全声明
    assert "Never invent an evidence_id" in prompt or "绝对禁止编造虚假 Evidence ID" in prompt
