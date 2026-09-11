# IRO_agent Agentic Harness P0/P1 收尾修复计划

> 日期：2026-09-11  
> 用途：直接交给本地 Coding AI 执行  
> 目标：修复当前 Agentic Investigation Harness 仍残留的 6 个关键问题，使生产运行真正达到“LLM 动态假设 + 动态取证 + Harness 约束”的状态。  
> 性质：**收尾修复，不再做大规模重构。**

---

# 0. 本轮范围

本轮只处理以下 6 项：

1. LLM 模式默认启用动态 Hypothesis。
2. Planner 可以新增 / 修改 / 淘汰 Hypothesis。
3. EvidenceEvaluator 只负责事实归一化，不再直接做粗糙因果判断。
4. Planner / Hypothesis Generator 与旧 SYSTEM_PROMPT、旧 Tool Calling 完全隔离。
5. 删除生产环境假的 PLC / Robot 证据，并移除 Agentic Planner 对旧 `diagnostic_pipeline` 的访问。
6. Planner Error 不再静默 fallback；Physical Escalation 必须经过 Harness Guardrail。

禁止扩大范围：

```text
× 不重写 RuntimeDispatcher
× 不重写 Evaluation Harness
× 不重写 Deep Bootstrap
× 不增加新模型
× 不增加新数据库
× 不新增 UI / Feishu 功能
× 不新增写权限
× 不做多 Agent
```

---

# 1. 执行前基线

执行：

```bash
git status
git rev-parse HEAD
pytest -q
```

阅读：

```text
iro_agent/investigation/harness.py
iro_agent/investigation/llm_planner.py
iro_agent/investigation/hypotheses.py
iro_agent/investigation/evaluator.py
iro_agent/investigation/models.py
iro_agent/investigation/tool_registry.py
iro_agent/investigation/physical_escalation.py
iro_agent/llm/glm_client.py
iro_agent/evaluation/runner.py
```

生成：

```text
docs/agentic_harness_p0_baseline_260911.md
```

记录：

- HEAD SHA
- pytest baseline
- `dynamic_hypotheses` 当前默认值
- Planner 当前调用的 GLM API
- DynamicHypothesisGenerator 当前调用的 GLM API
- production 默认 tool handlers
- `diagnostic_pipeline` 是否暴露给 Agentic Planner
- Planner Error 当前如何 fallback
- Physical Escalation 当前谁有最终批准权

---

# 2. Fix 1 — LLM 模式必须默认启用 Dynamic Hypothesis

## 当前问题

如果当前仍为：

```python
dynamic_hypotheses: bool = False
```

则即使：

```text
planner_mode = llm
```

初始 Hypothesis 仍可能来自固定模板。

这与 Agentic 模式冲突。

## 修改目标

生产逻辑改成：

```text
planner_mode == "llm"
→ dynamic hypotheses 必须启用
```

不要依赖调用方记得传：

```python
dynamic_hypotheses=True
```

推荐：

```python
if planner_mode == "llm":
    self.dynamic_hypotheses = True
else:
    self.dynamic_hypotheses = dynamic_hypotheses
```

更推荐直接取消 LLM 模式下这个可关闭开关。

## Legacy 规则

固定模板只允许：

```text
planner_mode = deterministic
```

使用。

禁止：

```text
LLM planner + deterministic initial hypotheses
```

作为生产默认。

## 测试

新增：

```text
tests/test_llm_mode_enables_dynamic_hypotheses.py
```

断言：

```text
planner_mode=llm
→ DynamicHypothesisGenerator called
→ fallback template not called
```

---

# 3. Fix 2 — PlannerDecision 增加 Hypothesis Updates

## 当前问题

Planner 当前只会：

```text
选择下一 Tool
或 Stop
```

但无法真正表达：

```text
新增假设
降低假设
反驳假设
淘汰假设
```

导致 Hypothesis 生命周期仍主要由 Python 规则决定。

## 修改 PlannerDecision Schema

建议新增：

```python
@dataclass
class HypothesisUpdate:
    action: str
    hypothesis_id: str | None
    statement: str | None
    confidence: float | None
    evidence_ids: list[str]
    reason: str
```

允许 action：

```text
ADD
REVISE
SUPPORT
CONTRADICT
RETIRE
MERGE
```

`PlannerDecision` 增加：

```python
hypothesis_updates: list[HypothesisUpdate]
```

## JSON 示例

```json
{
  "reasoning_summary": "新证据显示机器人在线，因此通信故障假设下降；需新增状态机闭锁假设。",
  "hypothesis_updates": [
    {
      "action": "CONTRADICT",
      "hypothesis_id": "H2",
      "statement": null,
      "confidence": 0.12,
      "evidence_ids": ["E003", "E004"],
      "reason": "heartbeat 与 callback 均为当前值"
    },
    {
      "action": "ADD",
      "hypothesis_id": null,
      "statement": "后端任务存在，但状态机可能处于禁止下发状态",
      "confidence": 0.31,
      "evidence_ids": ["E002"],
      "reason": "任务存在但无有效 dispatch"
    }
  ],
  "decision": {
    "action": "CALL_TOOL",
    "tool_name": "log_search",
    "arguments": {
      "keyword": "dispatch"
    }
  }
}
```

## Harness 约束

LLM 不能直接修改 State。

流程必须是：

```text
Planner
→ HypothesisUpdate schema validation
→ evidence_id validation
→ hypothesis_id validation
→ confidence range validation
→ HypothesisManager.apply_updates()
```

必须验证：

- `SUPPORT` / `CONTRADICT` 必须引用已存在 Evidence。
- `RETIRE` 必须引用现有 Hypothesis。
- `ADD` 不得重复已有 Hypothesis 的同义描述。
- confidence 范围 `0.0~1.0`。
- Planner 不得把用户 symptom 当 Evidence ID。

## 测试

新增：

```text
tests/test_planner_hypothesis_updates.py
tests/test_planner_can_add_hypothesis.py
tests/test_planner_can_retire_hypothesis.py
tests/test_invalid_evidence_reference_rejected.py
```

---

# 4. Fix 3 — EvidenceEvaluator 与因果判断彻底解耦

## 当前问题

如果仍存在：

```text
发现 ERROR
→ strongly_support(Hx)
```

或者：

```text
某关键词命中
→ confirm hypothesis
```

这种逻辑，Agentic Harness 仍然被专家规则控制。

## 新职责

`EvidenceEvaluator` 只负责：

```text
Raw Tool Result
↓
EvidenceRecord
```

包括：

```text
source
timestamp
raw_summary
normalized_fact
reliability
availability
provenance
error_type
```

错误做法：

```python
if "ERROR" in log:
    hypothesis_manager.strongly_support(target)
```

正确做法：

```python
EvidenceRecord(
    source="backend.log",
    normalized_fact="robot dispatch returned timeout",
    reliability=0.9,
    ...
)
```

然后下一轮 Planner 判断：

```text
E003 supports H2
E003 contradicts H1
```

## 可以保留的确定性解析

允许：

```text
HTTP 404
SQL 0 rows
process not running
heartbeat timestamp
PLC register value
config actual value
```

这些都是事实。

禁止直接从这些事实自动推出：

```text
root cause confirmed
```

## 测试

新增：

```text
tests/test_evidence_evaluator_no_causal_shortcut.py
tests/test_log_error_not_auto_root_cause.py
tests/test_evidence_fact_only.py
```

关键 Case：

```text
当前 hypothesis = robot communication failure

日志出现：
ERROR database retry
```

必须：

```text
不能因为存在 ERROR 就支持 robot hypothesis
```

---

# 5. Fix 4 — Planner 与旧 SYSTEM_PROMPT / Tool Calling 完全隔离

## 当前问题

如果：

```python
LLMInvestigationPlanner
→ glm_client.chat_completion(...)
```

而 `chat_completion()` 会自动：

```text
注入旧 SYSTEM_PROMPT
+
开放 Tools
+
启动内部 Tool Calling Loop
```

则 Planner 实际不是纯 Planner。

这会造成：

```text
Harness
→ Planner
→ 旧 Agent Tool Calling
→ Planner JSON
→ Harness 再 Tool Calling
```

属于双重 Agent Loop。

## 修改目标

新增独立纯 LLM 调用接口，例如：

```python
glm_client.complete_structured(
    system_prompt=PLANNER_SYSTEM_PROMPT,
    user_payload=...,
    schema=PlannerDecision,
    tools=None
)
```

或者：

```python
raw_completion(...)
```

硬要求：

```text
NO global legacy SYSTEM_PROMPT
NO tools
NO internal tool loop
NO automatic project_lookup/db_query
```

## DynamicHypothesisGenerator 同样修改

如果当前它也调用：

```python
chat_completion()
```

必须切换到纯结构化调用。

## Planner Prompt 只包含

- investigation policy
- state
- available tool definitions
- JSON schema

它“知道工具”，但不能直接执行工具。

## 测试

新增：

```text
tests/test_planner_has_no_tools.py
tests/test_planner_does_not_receive_general_system_prompt.py
tests/test_dynamic_hypothesis_generator_has_no_tool_loop.py
```

Mock 必须断言：

```text
planner model call tools == None / []
```

---

# 6. Fix 5 — 删除假的 PLC / Robot Evidence

## 当前问题

如果 production default tools 仍存在：

```python
plc_read -> {"status": "READ_SUCCESS", "val": 0}

robot_query -> {
    "status": "ONLINE",
    "state": "STANDBY"
}
```

这是严重问题。

它会把不存在的现场状态伪造成真实 Evidence。

## 正确策略 A（推荐）

未配置真实 Reader：

```text
不要注册该 Tool
```

ToolRegistry 中：

```text
plc_read
robot_query
```

只有在真实 adapter 可用时才出现。

Planner 根本看不到未配置工具。

## 正确策略 B

如果架构必须保留工具名：

返回：

```json
{
  "status": "UNAVAILABLE",
  "reason": "PLC reader is not configured"
}
```

然后 Evidence 正规化为：

```text
OBSERVABILITY_GAP
```

绝不能伪造：

```text
READ_SUCCESS
ONLINE
STANDBY
```

## 测试

新增：

```text
tests/test_no_fake_plc_evidence.py
tests/test_no_fake_robot_evidence.py
tests/test_unconfigured_reader_becomes_observability_gap.py
```

---

# 7. Fix 6A — 从 Agentic ToolRegistry 移除 diagnostic_pipeline

## 当前问题

如果 Planner 可以调用：

```text
diagnostic_pipeline
```

而它内部又执行：

```text
旧 DiagnosticOrchestrator 固定流程
```

则 Agentic Planner 可以重新钻回旧流程。

## 修改目标

在：

```text
planner_mode = llm
```

的 ToolRegistry 中不暴露：

```text
diagnostic_pipeline
investigation_pipeline
```

因为：

- `investigation_pipeline` 会递归进入 Harness。
- `diagnostic_pipeline` 会进入旧固定流程。

它们可保留用于：

```text
legacy benchmark
deterministic mode
manual debug
```

但不能成为 Agentic Planner 可选 Tool。

## 测试

新增：

```text
tests/test_agentic_registry_excludes_legacy_pipelines.py
```

断言 LLM Planner Tool Catalog 中不存在：

```text
diagnostic_pipeline
investigation_pipeline
```

---

# 8. Fix 6B — Planner Error 禁止静默 fallback

## 当前问题

如果：

```text
LLM Planner error
→ self.planner_mode = deterministic
→ EvidencePlanner
→ 继续回答
```

用户完全不知道 Agentic Planner 已失效。

Eval 也无法真实测到失败。

## 修改目标

默认生产行为：

```text
PLANNER_ERROR
→ stop
→ explicit failure state
```

内部：

```text
stop_reason = PLANNER_ERROR
```

输出：

```text
当前智能调查规划器未能完成有效规划，本次诊断未完成。
```

可以附：

```text
已获取的现有事实
```

但禁止伪装成完整诊断。

## 可选 Limited Mode

未来如果确实需要 fallback，必须显式：

```text
planner_mode = limited_deterministic
```

并在：

```text
trace
final report
metrics
```

中明确标记。

本轮默认不做自动 fallback。

## 测试

新增：

```text
tests/test_planner_error_does_not_fallback.py
```

---

# 9. Fix 6C — Physical Escalation 必须由 Harness 二次批准

## 当前问题

如果 LLM 返回：

```text
ESCALATE_PHYSICAL
```

就直接：

```text
physical_escalation_required = True
```

会绕过 Guardrail。

## 正确流程

```text
LLM Planner
→ REQUEST_HUMAN_PHYSICAL_CHECK

Harness
→ PhysicalEscalation.should_escalate(state)

YES
→ PHYSICAL_ESCALATION

NO
→ 拒绝升级
→ 继续取证 / OBSERVABILITY_GAP / INSUFFICIENT_EVIDENCE
```

## PhysicalEscalation 条件至少包含

```text
关键数字路径覆盖充分
+
当前数字证据无法解释现象
+
不存在关键 observability gap
+
没有未验证的高价值数字假设
```

## 测试

新增：

```text
tests/test_llm_cannot_self_approve_physical_escalation.py
tests/test_physical_escalation_guardrail.py
```

---

# 10. Harness 主循环最终目标

最终主循环应接近：

```python
state = initialize_state(...)

while True:
    stop = stop_conditions.evaluate(state)
    if stop.should_stop:
        break

    decision = llm_planner.plan(...)

    validated = planner_validator.validate(decision)

    if not validated.ok:
        state.stop_reason = "PLANNER_ERROR"
        break

    hypothesis_manager.apply_updates(
        validated.hypothesis_updates,
        evidence=state.evidence
    )

    if validated.action == "REQUEST_HUMAN_PHYSICAL_CHECK":
        if physical_escalation.should_escalate(state):
            state.stop_reason = "PHYSICAL_ESCALATION"
            break
        else:
            state.record_rejected_escalation(...)
            continue

    if validated.action == "CALL_TOOL":
        raw = tool_executor.execute(...)
        evidence = evidence_evaluator.normalize(raw)
        state.add_evidence(evidence)

    trace.record(...)
```

关键点：

```text
EvidenceEvaluator 不改 hypothesis
LLM Planner 提议 hypothesis update
Harness 验证后执行
```

---

# 11. Trace 必须新增字段

每轮至少保存：

```json
{
  "planner_call_mode": "pure_structured_llm",
  "hypothesis_updates_requested": [],
  "hypothesis_updates_applied": [],
  "hypothesis_updates_rejected": [],
  "selected_tool": "...",
  "tool_registered": true,
  "tool_result_availability": "AVAILABLE",
  "physical_escalation_requested": false,
  "physical_escalation_approved": false,
  "planner_error": null
}
```

这样现场可以明确判断：

```text
这一轮到底是 LLM 决定的，
还是 deterministic 规则决定的。
```

---

# 12. 关键行为验收

## Case A — Dynamic hypothesis 默认开启

输入：

```text
机器人不动
```

不得首先出现代码固定 H1~H5。

Trace 应：

```text
hypotheses_source = LLM
```

## Case B — 新 Evidence 产生新 Hypothesis

初始：

```text
Backend / PLC / Robot
```

后来发现：

```text
日志时间比系统时间慢 20 分钟
```

Planner 可以新增：

```text
stale log / clock drift
```

源码中无需预设。

## Case C — ERROR 不自动支持根因

Hypothesis：

```text
Robot communication error
```

Evidence：

```text
database connection ERROR
```

不得：

```text
strongly support robot communication error
```

## Case D — Planner 不能执行 Tool

Mock Planner 尝试内部 Tool Calling。

必须不存在这种通路。

Planner 只返回 JSON。

## Case E — 未配置 PLC Reader

Planner 需要 PLC 状态。

如果真实 Reader 不存在：

正确：

```text
Tool unavailable
→ Observability Gap
```

禁止：

```text
val=0
```

## Case F — Planner Error

LLM 返回非法 JSON 两次。

正确：

```text
PLANNER_ERROR
```

不能：

```text
switch deterministic
```

## Case G — Physical Escalation 被拒绝

LLM 请求物理检查。

但：

```text
PLC reader unavailable
```

存在关键 observability gap。

Harness 必须拒绝物理升级。

---

# 13. Evaluation 增加检查项

在当前 Evaluation Harness 增加：

```text
Dynamic Hypothesis Rate
Hypothesis Update Validity
Unsupported Hypothesis Update Rate
Causal Shortcut Violation
Planner Isolation Violation
Fake Evidence Violation
Legacy Pipeline Usage Rate
Silent Fallback Rate
Physical Escalation Override Rate
```

硬门槛：

```text
Fake Evidence Violation           = 0
Legacy Pipeline Usage in LLM mode = 0
Silent Fallback                   = 0
Planner internal tool calls       = 0
Physical guardrail bypass         = 0
```

---

# 14. 推荐 Commit 顺序

## Commit 1

```text
fix(investigation): enable dynamic hypotheses by default in llm mode
```

## Commit 2

```text
feat(investigation): allow planner-driven hypothesis lifecycle updates
```

## Commit 3

```text
refactor(evidence): separate fact normalization from causal judgment
```

## Commit 4

```text
refactor(llm): isolate planner and hypothesis generation from general agent tool loop
```

这是高风险核心修改，单独提交。

## Commit 5

```text
fix(tools): remove fake runtime evidence and legacy pipelines from agentic registry
```

## Commit 6

```text
fix(harness): prohibit silent planner fallback and enforce physical escalation guardrail
```

## Commit 7

```text
test(eval): add agentic harness p0 safety and behavior coverage
```

## Commit 8

```text
docs: document final agentic harness runtime semantics
```

---

# 15. 每个 Commit 的验收

每次：

```bash
pytest -q
iro-agent eval dev
iro-agent eval regression
```

另外人工至少执行：

```text
机器人不动
PLC相关故障
一个未知跨层故障
一个证据缺失故障
一个 Planner Error mock
一个物理层真实/模拟边界案例
```

任何 Critical Regression 失败：

```text
停止进入下一 Commit
```

---

# 16. 完成后源码检查

搜索：

```bash
grep -R "READ_SUCCESS" iro_agent/investigation
grep -R '"ONLINE"' iro_agent/investigation
grep -R "diagnostic_pipeline" iro_agent/investigation
grep -R "planner_mode = \"deterministic\"" iro_agent/investigation
grep -R "strongly_support" iro_agent/investigation/evaluator.py
grep -R "chat_completion" iro_agent/investigation
```

检查目标：

### `READ_SUCCESS` / `ONLINE`

不能是假的 production stub。

### `diagnostic_pipeline`

不能出现在 LLM Planner Tool Catalog。

### deterministic fallback

不能因 Planner Error 静默触发。

### `strongly_support`

EvidenceEvaluator 不应再基于字符串错误直接修改因果假设。

### `chat_completion`

Planner / DynamicHypothesisGenerator 不应再走带旧 Prompt + Tools 的通用 Agent 方法。

---

# 17. Definition of Done

## Dynamic Hypothesis

- [ ] LLM mode 默认动态生成 Hypothesis
- [ ] 固定模板只存在 deterministic baseline
- [ ] Planner 可 ADD / REVISE / SUPPORT / CONTRADICT / RETIRE / MERGE
- [ ] 更新必须引用合法 Evidence

## Evidence

- [ ] EvidenceEvaluator 只归一化事实
- [ ] ERROR 不直接等于根因
- [ ] Tool failure 单独表示
- [ ] provenance 完整

## Planner Isolation

- [ ] Planner 使用纯结构化 LLM 调用
- [ ] 无旧 SYSTEM_PROMPT
- [ ] 无 Tool Calling
- [ ] DynamicHypothesisGenerator 同样隔离

## Tools

- [ ] 无 fake PLC evidence
- [ ] 无 fake Robot evidence
- [ ] 未配置 Reader → unavailable / observability gap
- [ ] Agentic ToolRegistry 无 `diagnostic_pipeline`
- [ ] Agentic ToolRegistry 无 `investigation_pipeline`

## Failure Semantics

- [ ] Planner Error 明确停止
- [ ] 不静默 deterministic fallback
- [ ] Eval 能看到真实 Planner Error

## Physical

- [ ] LLM 只能请求物理升级
- [ ] Harness 才能批准
- [ ] 有 observability gap 时不能直接批准

## Runtime

- [ ] Feishu / CLI / Eval 保持共用同一 Harness
- [ ] 所有 P0 修复不破坏现有 RuntimeDispatcher

---

# 18. 最终交付报告

完成后生成：

```text
docs/agentic_harness_p0_fix_result_260911.md
```

必须包含：

1. HEAD before / after
2. Commit 列表
3. 6 项问题逐项是否完成
4. PlannerDecision 新 schema
5. Hypothesis lifecycle
6. Planner 纯 LLM 调用方式
7. ToolRegistry 最终列表
8. 哪些 Reader 是真实的，哪些 unavailable
9. Planner Error 行为
10. Physical Escalation 审批链
11. pytest 结果
12. DEV / Regression Eval 结果
13. 至少 6 个现场 trajectory
14. 所有仍存在的 deterministic 逻辑
15. 所有仍存在的 fake/mock/stub
16. 下一阶段遗留问题

---

# 19. 给本地 AI 的最终指令

本轮不是继续“增加 Agent 功能”。

要做的是把当前已经存在的 Agentic 架构彻底收口：

> **LLM 负责提出和修改假设、决定下一条证据；Harness 负责验证、安全、执行、记录和停止；Evidence 层只负责提供事实。**

特别禁止以下三种“看起来 Agentic，实际仍是规则系统”的做法：

```text
1. LLM 选工具，但 Hypothesis 仍由固定模板决定。
2. LLM 看 Evidence，但 Python 用 ERROR/关键词替它决定因果。
3. Planner 出错后偷偷切回 deterministic，用户和 Eval 都不知道。
```

完成标准：

> 面对一个没有固定 CaseType、没有固定 Hypothesis 模板、没有固定排查步骤的新故障，LLM 能自主提出可证伪假设；每得到一条真实 Evidence 后能改变假设和下一步工具；所有操作经过 Harness 安全验证；证据不足时明确停止；未配置的物理/设备 Reader 不产生任何虚假事实。

达到以上标准后，IRO_agent 第一版 Agentic Investigation Harness 才视为真正完成。
