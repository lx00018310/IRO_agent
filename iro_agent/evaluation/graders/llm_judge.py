import json
from typing import Optional, List, Any
from iro_agent.evaluation.models import EvalCase, GradeDetail
from iro_agent.investigation.models import InvestigationReport


class SemanticLLMJudge:
    """
    语义等价性与裁判评测器 (Semantic LLM Judge)
    在隔离的独立评测上下文中，核验诊断结论与标准答案 (Ground Truth) 的语义等价性。
    Judge 拥有 Ground Truth 权限，Agent Context 绝对物理隔离。
    若未注入 LLM Client 或在离线单元测试环境下，采用确定性语义相似度启发式作为兜底。
    """

    @classmethod
    def judge(
        cls,
        case: EvalCase,
        report: InvestigationReport,
        llm_client: Optional[Any] = None,
    ) -> GradeDetail:
        reported_answer = (report.primary_root_cause or "").strip()
        acceptable_causes = case.expectation.acceptable_root_causes

        # 1. 若用例未限制具体根因，默认满分通过
        if not acceptable_causes:
            return GradeDetail(
                name="semantic_judge",
                score=1.0,
                passed=True,
                details="用例未设定特定根因约束",
            )

        # 2. 如果提供了独立 Judge LLM Client，发起隔离的 Judge Prompt 调用
        if llm_client and hasattr(llm_client, "chat_completion"):
            try:
                judge_prompt = f"""你是一名严格的工控系统故障诊断评测裁判 (Judge)。
请判断【待评估诊断结论】与【标准可接受根因】在工程语义上是否等价或正确命中。

【故障现象】: {case.input.get("symptom", "")}
【标准可接受根因】: {json.dumps(acceptable_causes, ensure_ascii=False)}
【待评估诊断结论】: {reported_answer}

请严格按 JSON 格式回复，包含：
{{"matched": true/false, "score": 1.0到0.0之间的浮点数, "reason": "简明裁决理由"}}"""
                resp = llm_client.chat_completion([{"role": "user", "content": judge_prompt}])
                # 解析返回
                if "{" in resp and "}" in resp:
                    json_str = resp[resp.find("{"):resp.rfind("}")+1]
                    data = json.loads(json_str)
                    return GradeDetail(
                        name="semantic_judge",
                        score=float(data.get("score", 1.0 if data.get("matched") else 0.0)),
                        passed=bool(data.get("matched", False)),
                        details=str(data.get("reason", "LLM Judge 判定完成")),
                    )
            except Exception:
                pass

        # 3. 确定性语义启发式比对 (离线 / 兜底模式)
        reported_lower = reported_answer.lower()
        matched = False
        matched_cause = ""
        for arc in acceptable_causes:
            arc_lower = arc.lower()
            # 完全包含或子词核心重合
            if arc_lower in reported_lower:
                matched = True
                matched_cause = arc
                break
            # 关键词组重合度
            arc_keywords = [w for w in arc_lower.replace("_", " ").split() if len(w) > 1]
            if arc_keywords and all(kw in reported_lower for kw in arc_keywords):
                matched = True
                matched_cause = arc
                break

        score = 1.0 if matched else 0.0
        details = f"语义匹配成功，命中根因: [{matched_cause}]" if matched else f"语义未命中，期望根因: {acceptable_causes}"

        return GradeDetail(
            name="semantic_judge",
            score=score,
            passed=matched,
            details=details,
            violations=[] if matched else [f"实际诊断 [{reported_answer}] 未命中任一标准根因: {acceptable_causes}"],
        )
