from typing import Dict, Any, Optional, List
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceEvaluationResult,
    HypothesisStatus,
    EvidenceRecord,
)
from iro_agent.investigation.hypotheses import HypothesisManager


class EvidenceEvaluator:
    """证据单项结果标准化评估器 (Evidence Evaluator)"""

    @classmethod
    def evaluate_step(
        cls,
        step: InvestigationStep,
        tool_output: Any,
        hypo_mgr: HypothesisManager,
    ) -> EvidenceEvaluationResult:
        step.result = tool_output
        verdict = "INCONCLUSIVE"
        detail = ""
        impacted: Dict[str, str] = {}

        # 1. 结果为空或异常判定
        if not tool_output or (isinstance(tool_output, dict) and tool_output.get("error")):
            verdict = "MISSING"
            detail = f"工具 {step.tool} 未采集到有效证据或执行异常: {tool_output}"
            step.evaluation = verdict
            return EvidenceEvaluationResult(step_id=step.step_id, verdict=verdict, detail=detail)

        out_str = str(tool_output)

        # 2. 数据库任务存在性评估
        if step.evidence_type in ("task_creation_state", "dock_task_status"):
            if isinstance(tool_output, list) and len(tool_output) > 0:
                verdict = "FACT"
                detail = f"数据库证实存在活跃或最新任务记录 (共 {len(tool_output)} 条)"
                # 反驳 "未创建任务" 假设 H1/H2
                for h_id in step.hypothesis_ids:
                    h = hypo_mgr.get_hypothesis(h_id)
                    if h and ("未创建" in h.description or "未成功创建" in h.description):
                        hypo_mgr.rule_out(h_id, reason="数据库已存在主任务记录", evidence=detail)
                        impacted[h_id] = HypothesisStatus.RULED_OUT.value
                    elif h and ("拒绝迁移" in h.description or "校验未通过" in h.description):
                        hypo_mgr.strongly_support(h_id, reason="状态表记录支持状态停滞", evidence=detail)
                        impacted[h_id] = HypothesisStatus.STRONGLY_SUPPORTED.value
            else:
                verdict = "SUPPORTING"
                detail = "数据库未检索到有效主任务记录"
                for h_id in step.hypothesis_ids:
                    h = hypo_mgr.get_hypothesis(h_id)
                    if h and ("未创建" in h.description or "未成功创建" in h.description):
                        hypo_mgr.confirm(h_id, reason="数据库确实无任务记录", evidence=detail)
                        impacted[h_id] = HypothesisStatus.CONFIRMED.value

        # 3. 日志报错与通信异常评估
        elif "log" in step.evidence_type or step.tool == "log_search":
            if isinstance(tool_output, list) and len(tool_output) > 0:
                has_error = any(
                    isinstance(item, dict) and item.get("level") == "ERROR" or "exception" in str(item).lower()
                    for item in tool_output
                )
                if has_error:
                    verdict = "FACT"
                    detail = f"捕获到明确系统运行报错与异常堆栈 (共 {len(tool_output)} 条日志)"
                    for h_id in step.hypothesis_ids:
                        hypo_mgr.strongly_support(h_id, reason="日志捕获直接报错", evidence=detail)
                        impacted[h_id] = HypothesisStatus.STRONGLY_SUPPORTED.value
                else:
                    verdict = "SUPPORTING"
                    detail = f"检索到通信流水，但无致命 ERROR 级别异常 (共 {len(tool_output)} 条)"
            else:
                verdict = "MISSING"
                detail = "指定关键词日志未见异常或无匹配项"

        # 4. 配置检索评估
        elif step.tool == "config_lookup":
            if isinstance(tool_output, list) and len(tool_output) > 0:
                verdict = "FACT"
                detail = f"查明目标配置项及其覆盖规则: {len(tool_output)} 项"
                for h_id in step.hypothesis_ids:
                    hypo_mgr.strongly_support(h_id, reason="已定位有效配置及其生效优先级", evidence=detail)
                    impacted[h_id] = HypothesisStatus.STRONGLY_SUPPORTED.value
            else:
                verdict = "MISSING"
                detail = "未发现匹配的有效配置项"

        else:
            verdict = "FACT" if tool_output else "MISSING"
            detail = f"工具 {step.tool} 执行完毕"

        step.evaluation = verdict
        return EvidenceEvaluationResult(
            step_id=step.step_id,
            verdict=verdict,
            detail=detail,
            impacted_hypotheses=impacted,
        )

    @classmethod
    def create_evidence_record(
        cls,
        step: InvestigationStep,
        tool_output: Any,
        eval_res: EvidenceEvaluationResult,
    ) -> EvidenceRecord:
        """根据排查步骤执行与评估结果标准化生成客观 EvidenceRecord"""
        is_error = False
        error_type = None
        if isinstance(tool_output, dict) and tool_output.get("error"):
            is_error = True
            error_type = "tool_failure"

        supports: List[str] = []
        contradicts: List[str] = []
        for h_id, status in eval_res.impacted_hypotheses.items():
            if status in (HypothesisStatus.CONFIRMED.value, HypothesisStatus.STRONGLY_SUPPORTED.value):
                supports.append(h_id)
            elif status == HypothesisStatus.RULED_OUT.value:
                contradicts.append(h_id)

        reliability = 0.0 if is_error else (0.95 if eval_res.verdict == "FACT" else 0.7)
        relevance = 0.9 if eval_res.impacted_hypotheses else 0.6

        return EvidenceRecord(
            evidence_id=f"EV_{step.step_id}",
            source_type=step.tool,
            source_name=step.evidence_type,
            tier=step.evidence_tier,
            query=step.tool_args,
            raw_summary=eval_res.detail,
            reliability=reliability,
            relevance=relevance,
            supports=supports,
            contradicts=contradicts,
            is_error=is_error,
            error_type=error_type,
            provenance={"tool": step.tool, "step_id": step.step_id, "verdict": eval_res.verdict},
        )

