import re
from typing import Dict, Any, Optional, List, Tuple
from iro_agent.investigation.models import (
    InvestigationStep,
    EvidenceEvaluationResult,
    HypothesisStatus,
    EvidenceRecord,
)
from iro_agent.investigation.hypotheses import HypothesisManager


class EvidenceEvaluator:
    """
    证据客观事实提取器 (Objective Evidence Evaluator)
    分为两个清晰阶段：
    阶段 1: 客观事实化提取 (extract_fact) - 提取纯粹观察结果，超时/异常显式判定为 OBSERVABILITY_GAP 或 TOOL_EXECUTION_ERROR；
    阶段 2: 事实定性与评级 (judge_causality / evaluate_step) - 判定证据的可用性/客观性（FACT, MISSING, OBSERVABILITY_GAP），
            绝不粗糙做因果映射，绝不直接操作 HypothesisManager 修改假设状态，
            绝不因为日志中出现 'ERROR' 字符串就自动支持当前假设或认定根本原因。
            因果归因与假设状态转移严格交由规划器 (Planner) 基于完整证据链统一评估。
    """

    TIMEOUT_AND_GAP_PATTERNS = [
        r"timeout", r"timed\s*out", r"connection\s*refused", r"unreachable",
        r"not\s*connected", r"network\s*error", r"socket\s*error", r"econnreset",
        r"connection\s*reset", r"observability_gap"
    ]

    @classmethod
    def extract_fact(cls, step: InvestigationStep, tool_output: Any) -> Tuple[bool, Optional[str], str]:
        """
        阶段 1: 客观事实化提取
        返回: (is_error, error_type, fact_summary)
        """
        if tool_output is None:
            return True, "OBSERVABILITY_GAP", f"工具 {step.tool} 返回为空，未采集到有效数据"

        if isinstance(tool_output, dict) and tool_output.get("error"):
            err_msg = str(tool_output.get("error"))
            err_lower = err_msg.lower()
            is_gap = any(re.search(p, err_lower) for p in cls.TIMEOUT_AND_GAP_PATTERNS)
            error_type = "OBSERVABILITY_GAP" if is_gap else "TOOL_EXECUTION_ERROR"
            return True, error_type, f"工具 {step.tool} 执行发生异常 ({error_type}): {err_msg}"

        # 正常输出提取结构化事实摘要
        if isinstance(tool_output, list):
            return False, None, f"获取到 {len(tool_output)} 条记录"
        elif isinstance(tool_output, dict):
            keys_str = ", ".join(list(tool_output.keys())[:5])
            return False, None, f"获取到字典数据，包含键: [{keys_str}]"
        else:
            return False, None, f"输出: {str(tool_output)[:100]}"

    @classmethod
    def judge_causality(
        cls,
        step: InvestigationStep,
        tool_output: Any,
        is_error: bool,
        error_type: Optional[str],
        fact_summary: str,
        hypo_mgr: Optional[HypothesisManager] = None,
    ) -> EvidenceEvaluationResult:
        """
        阶段 2: 证据事实定性与客观评级 (不直接修改假设状态，消除粗糙因果捷径)
        """
        impacted: Dict[str, str] = {}

        # 1. 若工具异常或观测缺口，判定为 OBSERVABILITY_GAP 或 MISSING，绝不影响假设
        if is_error:
            verdict = "OBSERVABILITY_GAP" if error_type == "OBSERVABILITY_GAP" else "MISSING"
            detail = fact_summary
            step.evaluation = verdict
            return EvidenceEvaluationResult(
                step_id=step.step_id,
                verdict=verdict,
                detail=detail,
                impacted_hypotheses=impacted,
            )

        verdict = "INCONCLUSIVE"
        detail = ""

        # 2. 数据库任务存在性评估：仅记录客观事实，不自动改变假设状态
        if step.evidence_type in ("task_creation_state", "dock_task_status") or step.tool == "db_query":
            rows = tool_output if isinstance(tool_output, list) else (tool_output.get("rows", []) if isinstance(tool_output, dict) else [])
            if rows:
                verdict = "FACT"
                detail = f"数据库证实存在记录 (共 {len(rows)} 条)"
            else:
                verdict = "FACT"
                detail = "数据库未检索到有效记录 (0 条)"

        # 3. 日志检索评估：仅记录是否有日志匹配与报错堆栈事实，不自动给假设打支持标签
        elif "log" in step.evidence_type or step.tool == "log_search":
            logs = tool_output if isinstance(tool_output, list) else (tool_output.get("logs", []) if isinstance(tool_output, dict) else [])
            if logs:
                verdict = "FACT"
                has_error = any(
                    isinstance(item, dict) and item.get("level") == "ERROR" or "error" in str(item).lower() or "exception" in str(item).lower()
                    for item in logs
                )
                if has_error:
                    detail = f"日志检索完成，包含报错或异常堆栈 (共 {len(logs)} 条)"
                else:
                    detail = f"日志检索完成，未见致命报错 (共 {len(logs)} 条)"
            else:
                verdict = "MISSING"
                detail = "指定关键词日志未见匹配项"

        # 4. 配置检索评估
        elif step.tool == "config_lookup":
            configs = tool_output if isinstance(tool_output, list) else (tool_output.get("configs", []) if isinstance(tool_output, dict) else [])
            if configs:
                verdict = "FACT"
                detail = f"查明目标配置项: {len(configs)} 项"
            else:
                verdict = "MISSING"
                detail = "未发现匹配的有效配置项"

        # 5. PLC 读取评估
        elif step.tool == "plc_read":
            verdict = "FACT"
            detail = f"PLC 端口读取完成: {tool_output}"

        # 6. 机器人状态查询评估
        elif step.tool == "robot_query":
            verdict = "FACT"
            detail = f"机器人状态查询完成: {tool_output}"

        else:
            verdict = "FACT" if tool_output else "MISSING"
            detail = f"工具 {step.tool} 执行完毕: {fact_summary}"

        step.evaluation = verdict
        return EvidenceEvaluationResult(
            step_id=step.step_id,
            verdict=verdict,
            detail=detail,
            impacted_hypotheses=impacted,
        )

    @classmethod
    def evaluate_step(
        cls,
        step: InvestigationStep,
        tool_output: Any,
        hypo_mgr: Optional[HypothesisManager] = None,
    ) -> EvidenceEvaluationResult:
        """客观事实提取入口：先后执行事实提取与事实定性"""
        step.result = tool_output
        is_error, error_type, fact_summary = cls.extract_fact(step, tool_output)
        return cls.judge_causality(
            step=step,
            tool_output=tool_output,
            is_error=is_error,
            error_type=error_type,
            fact_summary=fact_summary,
            hypo_mgr=hypo_mgr,
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
            err_msg = str(tool_output.get("error")).lower()
            is_gap = any(re.search(p, err_msg) for p in cls.TIMEOUT_AND_GAP_PATTERNS)
            error_type = "OBSERVABILITY_GAP" if is_gap else "TOOL_FAILURE"

        reliability = 0.0 if is_error else (0.95 if eval_res.verdict == "FACT" else 0.7)
        relevance = 0.8 if eval_res.verdict == "FACT" else 0.5

        return EvidenceRecord(
            evidence_id=f"EV_{step.step_id}",
            source_type=step.tool,
            source_name=step.evidence_type,
            tier=step.evidence_tier,
            query=step.tool_args,
            raw_summary=eval_res.detail,
            normalized_fact=eval_res.detail,
            reliability=reliability,
            relevance=relevance,
            supports=[],
            contradicts=[],
            is_error=is_error,
            error_type=error_type,
            provenance={"tool": step.tool, "step_id": step.step_id, "verdict": eval_res.verdict},
        )
