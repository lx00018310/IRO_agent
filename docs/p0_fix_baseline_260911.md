# IRO_agent P0 修复执行前基线记录 (2026-09-11)

- **基线 HEAD SHA**: `852ef2a74c65e68f5be07966e2aec6337bdd7081`
- **Pytest Baseline**: `195 passed, 8 warnings in 73.21s`
- **当前 Planner Fallback 现状**:
  - `harness.py` 初始化时若探测到 API key 无效仍有将 `self.planner_mode` 切为 `deterministic` 的旧逻辑；
  - 目标：在 `planner_mode == "llm"` 时必须 Fail Closed，严禁自动切模式。
- **当前 Dynamic Hypothesis Fallback 现状**:
  - `hypotheses.py` 中 `HypothesisManager.__init__` 若动态生成失败会调用 `self._generate_fallback_hypotheses()`；
  - 目标：在 LLM 模式下若动态假设生成失败，显式终止并标定 `stop_reason = HYPOTHESIS_GENERATION_ERROR`，绝不进入固定模板。
- **ToolRegistry vs 实际 Reader 签名差异**:
  - `db_query`: Registry 参数为 `sql`，底层 `DatabaseReader.execute_query` 入参为 `query`；
  - `log_search`: Registry 参数为 `limit`，底层 `LogReader.search_logs` 入参为 `max_results`；
  - 目标：在 Harness 中为全部工具建立显式 adapter，实现 Registry schema 与底层参数的双向解耦与 100% 对齐。
- **Planner Prompt Evidence 格式现状**:
  - 当前 Prompt 模板中证据格式为 `- [{tier_val}] {ev.source_name}: {ev.raw_summary}`，未暴露 `evidence_id`；
  - 目标：格式化暴露 `[{ev.evidence_id}] [{tier_val}] {ev.source_name}: {ev.normalized_fact}`，约束模型严格引用。
- **CONVERGE 处理现状**:
  - 当前 LLM 返回 `DecisionAction.CONVERGE` 直接 break 结案；
  - 目标：引入 `StopConditions.validate_convergence(state, hypo_mgr)` 二次审批，证据不足时驳回收敛请求。
