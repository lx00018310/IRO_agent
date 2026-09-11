# IRO_agent P0 修复计划

> 日期：2026-09-11  
> 用途：直接交给本地 Coding AI 执行  
> 范围：**只修 P0，不处理 Eval Fixture、Trace 持久化等 P1 问题**  
> 目标：修复当前 Agentic Investigation Harness 中会直接影响真实运行正确性的 4 个问题。

---

# 0. 本轮只处理 4 个 P0

1. **彻底禁止 Agentic 模式静默降级到 deterministic**
2. **修正 Tool Contract 参数不一致**
3. **Planner Prompt 显式提供 Evidence ID**
4. **LLM 的 CONVERGE 必须经过 Harness Guardrail 二次审批**

除此之外，不改：

```text
× Evaluation Fixture
× Trace 持久化
× Deep Bootstrap
× Feishu 功能
× UI
× 新模型
× 新 Reader
× 数据集结构
```

---

# 1. 执行前基线

先执行：

```bash
git status
git rev-parse HEAD
pytest -q
```

重点阅读：

```text
iro_agent/investigation/harness.py
iro_agent/investigation/llm_planner.py
iro_agent/investigation/hypotheses.py
iro_agent/investigation/tool_registry.py
iro_agent/investigation/models.py
iro_agent/investigation/stop_conditions.py
iro_agent/readers/database_reader.py
iro_agent/readers/log_reader.py
```

生成：

```text
docs/p0_fix_baseline_260911.md
```

记录：

- HEAD SHA
- pytest baseline
- 当前 planner fallback 逻辑
- 当前 dynamic hypothesis fallback 逻辑
- ToolRegistry 参数 schema
- 实际 Reader 函数签名
- Planner Prompt 当前 Evidence 格式
- 当前 CONVERGE 处理逻辑

---

# 2. P0-1 — 禁止 Agentic → Deterministic 静默降级

## 当前风险

如果存在：

```text
LLM 不可用
→ planner_mode 改成 deterministic
```

或：

```text
DynamicHypothesisGenerator 失败
→ fallback 固定模板
```

则用户看到的仍可能是旧规则流程，却不知道 Agentic 模式已经失效。

---

## 修改目标

在：

```text
planner_mode = "llm"
```

时必须 Fail Closed。

### Planner 初始化失败

正确：

```text
AGENTIC_PLANNER_UNAVAILABLE
```

不要：

```text
自动切 deterministic
```

### Dynamic Hypothesis 失败

正确：

```text
HYPOTHESIS_GENERATION_ERROR
```

停止当前诊断。

不要：

```text
_generate_fallback_hypotheses()
```

---

## deterministic 模式保留方式

固定模板可以继续保留，但只能显式使用：

```text
planner_mode = "deterministic"
```

不能由 LLM 模式自动切换。

---

## 最终行为

```text
LLM mode
   ↓
Planner unavailable / invalid
   ↓
明确失败
   ↓
stop_reason = PLANNER_ERROR
```

或者：

```text
Dynamic hypothesis generation failed
   ↓
stop_reason = HYPOTHESIS_GENERATION_ERROR
```

---

## 测试

新增：

```text
tests/test_no_silent_planner_fallback.py
tests/test_no_silent_hypothesis_fallback.py
```

必须断言：

```text
LLM planner error
→ deterministic planner NOT called
```

以及：

```text
dynamic hypothesis error
→ fallback template NOT called
```

---

# 3. P0-2 — 修正 Tool Contract 参数

## 当前风险

Planner 看到的 Tool Schema 与真实 Reader 参数不一致时，会产生：

```text
TOOL_EXECUTION_ERROR
```

例如当前需要重点确认：

```text
db_query
ToolRegistry: sql
DatabaseReader: query
```

以及：

```text
log_search
ToolRegistry: limit
LogReader: max_results
```

---

## 修改原则

必须建立唯一 Tool Contract。

推荐：

```text
ToolRegistry schema
=
ToolExecutor adapter schema
```

不要让 Planner 直接依赖 Reader 原始函数签名。

---

## 推荐做法

在 Harness / ToolExecutor 中为每个 Tool 提供 adapter。

例如：

```python
def db_query_adapter(sql: str):
    return database_reader.execute_query(query=sql)
```

```python
def log_search_adapter(keyword: str, limit: int = 20):
    return log_reader.search_logs(
        keyword=keyword,
        max_results=limit
    )
```

这样 Planner 永远只面对统一 schema。

---

## 不建议

不要简单把所有 Registry 字段改成底层 Reader 参数名后结束。

因为以后 Reader 内部签名变化，会再次污染 Planner Contract。

应该：

```text
Planner Contract
→ Adapter
→ Reader
```

---

## 本轮至少核对全部 Agentic Tool

检查：

```text
project_lookup
code_search
config_lookup
db_query
db_describe
log_search
version_current
plc_read
robot_query
```

确认：

```text
ToolRegistry arguments
=
adapter arguments
```

---

## 测试

新增：

```text
tests/test_tool_contract_db_query.py
tests/test_tool_contract_log_search.py
tests/test_agentic_tool_contracts.py
```

要求：

```text
Registry 中每个 Tool
→ 用最小合法参数执行 adapter
→ 不出现 unexpected keyword argument
```

---

# 4. P0-3 — Planner Prompt 必须提供 Evidence ID

## 当前风险

Planner 需要输出：

```text
SUPPORT
CONTRADICT
RETIRE
```

并引用：

```text
evidence_ids
```

但 Prompt 如果只提供：

```text
source
summary
tier
```

而没有：

```text
EV_xxx
```

模型只能猜 Evidence ID。

随后 Validator 会拒绝。

---

## 修改目标

Planner Prompt 中每条 Evidence 必须明确：

```text
evidence_id
source
timestamp
normalized_fact
reliability
availability
```

例如：

```json
{
  "evidence_id": "EV_003",
  "source": "backend.log",
  "timestamp": "2026-09-11T14:21:32",
  "fact": "robot dispatch timeout",
  "reliability": 0.9,
  "availability": "AVAILABLE"
}
```

---

## Hypothesis 也必须有明确 ID

Planner 输入：

```json
{
  "id": "H2",
  "statement": "Robot communication failure",
  "confidence": 0.42,
  "status": "ACTIVE",
  "supporting_evidence_ids": ["EV_001"],
  "contradicting_evidence_ids": []
}
```

---

## Prompt 中明确约束

写清楚：

```text
Only use evidence_ids that appear in the provided evidence list.
Never invent an evidence_id.
```

以及：

```text
Only reference hypothesis_id values that appear in the hypothesis list,
except when action=ADD.
```

---

## Validator 保持严格

不要因为 Planner 以前拿不到 ID 就放宽 Validator。

正确做法是：

```text
Prompt 提供正确 ID
+
Validator 继续严格拒绝虚构 ID
```

---

## 测试

新增：

```text
tests/test_planner_prompt_contains_evidence_ids.py
tests/test_planner_uses_valid_evidence_ids.py
```

Mock Planner 输入中必须可见：

```text
EV_001
EV_002
...
```

---

# 5. P0-4 — CONVERGE 必须经过 Harness Guardrail

## 当前风险

如果 LLM 返回：

```text
CONVERGE
```

Harness 直接：

```text
break
```

则模型可以在证据不足时自行宣布完成。

Physical Escalation 已经是：

```text
LLM request
→ Harness approval
```

CONVERGE 也必须同样处理。

---

## 新流程

```text
LLM Planner
→ REQUEST_CONVERGENCE

Harness
→ StopConditions.validate_convergence(state)

YES
→ STOP_CONFIRMED / STOP_SUPPORTED

NO
→ reject convergence
→ record reason
→ continue investigation
```

---

## Confirmed 条件

至少满足之一：

### 条件 A

```text
1 条 Source-of-Truth 级直接证据
```

### 条件 B

```text
2 条独立高质量证据
+
无强反证
```

并且最终核心 Claim 必须绑定 Evidence ID。

---

## Supported 条件

允许：

```text
Top hypothesis 明显领先
+
至少有实质 Evidence
+
不存在强反证
```

但最终措辞只能：

```text
“当前最可能”
```

不能写：

```text
“已经确认”
```

---

## Evidence 不足

如果 LLM 想 converge，但 Guardrail 不允许：

```text
convergence_rejected = True
reason = INSUFFICIENT_SUPPORT
```

继续下一轮。

---

## 防无限循环

如果连续：

```text
2 次 convergence 被拒绝
```

且没有新的 Evidence：

```text
STOP_INSUFFICIENT_EVIDENCE
```

避免模型反复申请收敛。

---

## 测试

新增：

```text
tests/test_llm_cannot_self_approve_convergence.py
tests/test_convergence_requires_evidence.py
tests/test_supported_vs_confirmed_convergence.py
```

关键 Case：

### Case A

只有 1 条低可靠日志：

```text
LLM asks CONVERGE
```

必须拒绝。

### Case B

2 条独立高质量证据：

```text
LLM asks CONVERGE
```

允许。

---

# 6. 推荐 Commit 顺序

## Commit 1

```text
fix(agentic): prohibit silent deterministic fallback
```

内容：

- planner fail closed
- hypothesis generator fail closed
- tests

---

## Commit 2

```text
fix(tools): align agentic tool contracts with runtime adapters
```

内容：

- db_query adapter
- log_search adapter
- 全量 Tool Contract 检查
- tests

---

## Commit 3

```text
fix(planner): expose evidence ids and hypothesis ids in planner context
```

内容：

- Planner Prompt
- schema
- tests

---

## Commit 4

```text
fix(harness): require guardrail approval for convergence
```

内容：

- convergence validation
- rejected convergence handling
- tests

---

# 7. 每个 Commit 验收

每次执行：

```bash
pytest -q
iro-agent eval dev
iro-agent eval regression
```

然后人工执行：

```text
1. 一个正常 Robot 故障
2. 一个 DB 查询故障
3. 一个 log_search 故障
4. 一个 Planner Error mock
5. 一个 Hypothesis Generator Error mock
6. 一个证据不足但 LLM 尝试 CONVERGE 的案例
```

---

# 8. 源码检查

完成后搜索：

```bash
grep -R "planner_mode.*deterministic" iro_agent/investigation
grep -R "_generate_fallback_hypotheses" iro_agent/investigation
grep -R "execute_query" iro_agent/investigation
grep -R "search_logs" iro_agent/investigation
grep -R "CONVERGE" iro_agent/investigation
```

检查：

### deterministic

LLM error 路径不得静默切换。

### fallback hypotheses

LLM 模式失败不得自动进入固定模板。

### Tool contracts

所有 Planner Tool 必须通过 adapter。

### CONVERGE

不能存在：

```text
if decision == CONVERGE:
    break
```

这种无 Guardrail 路径。

---

# 9. Definition of Done

## Fail Closed

- [ ] Planner Error 不切 deterministic
- [ ] Hypothesis Generator Error 不进固定模板
- [ ] 用户能明确知道 Agentic 调查失败

## Tool Contract

- [ ] db_query 参数一致
- [ ] log_search 参数一致
- [ ] 所有 Agentic Tool 都通过 contract test
- [ ] 无 unexpected keyword argument

## Evidence ID

- [ ] Planner Prompt 有 Evidence ID
- [ ] Planner Prompt 有 Hypothesis ID
- [ ] Planner 不需要猜 ID
- [ ] Validator 继续严格拒绝非法引用

## Convergence

- [ ] LLM 只能申请收敛
- [ ] Harness 最终批准
- [ ] Confirmed / Supported 分开
- [ ] Evidence 不足时拒绝收敛
- [ ] rejected convergence 可追踪

---

# 10. 最终交付文档

生成：

```text
docs/p0_fix_result_260911.md
```

必须包含：

1. Before / After HEAD
2. 4 个 P0 是否完成
3. 修改的文件
4. Commit 列表
5. Tool Contract 最终表
6. Planner 输入 Evidence 示例
7. Planner Error 行为
8. Hypothesis Generation Error 行为
9. CONVERGE 审批链
10. pytest 结果
11. DEV / Regression 结果
12. 6 个现场测试结果
13. 仍存在的 P1 问题

---

# 11. 最终执行原则

本轮判断是否成功，只看 4 件事：

```text
1. Agentic 模式坏了时，系统是否明确失败，而不是偷偷跑旧流程。
2. Planner 选择 db/log 工具后，是否能真实执行而不是参数报错。
3. Planner 修改 Hypothesis 时，是否能准确引用真实 Evidence ID。
4. LLM 想结束调查时，Harness 是否仍然拥有最终批准权。
```

这 4 项全部完成后，P0 才算关闭。
