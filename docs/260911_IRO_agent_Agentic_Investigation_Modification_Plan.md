# IRO_agent Agentic Investigation Harness 修改计划

> 日期：2026-09-11  
> 用途：直接交给本地 Coding AI 执行  
> 性质：针对当前 main 的增量修改，不推倒重写  
> 核心目标：解决“仓库里已经有 Investigation Harness，但生产飞书仍按原有固定流程运行”的问题。

---

# 0. 本轮只解决三个问题

当前系统已经有 InvestigationHarness、HypothesisManager、EvidencePlanner、EvidenceEvaluator、StopConditions、Evaluation Harness、Trajectory、Reader/Tool 等基础设施。

本轮只处理：

1. **生产入口统一**：飞书、CLI、Eval 的故障诊断必须进入同一个 InvestigationHarness。
2. **LLM 真正规划**：每得到一条新证据，LLM 根据当前状态决定下一条最有价值的证据，而不是 Python 的 `if/elif` 决定固定路径。
3. **Hypothesis 动态化**：假设由 LLM 根据项目知识、用户症状和证据生成/新增/降低/淘汰，HypothesisManager 只负责状态管理。

本轮禁止扩大范围：

- 不重写整个仓库。
- 不重写 Evaluation Harness。
- 不增加 Feishu 新业务功能。
- 不做 Dashboard。
- 不增加新模型供应商。
- 不引入向量数据库/RAG 平台。
- 不新增 PLC/Robot/DB 写权限。
- 不做多 Agent 群聊。
- 不通过堆更多 CaseType/关键词规则解决失败案例。

---

# 1. 开始编码前必须重新确认 HEAD

先执行：

```bash
git status
git rev-parse HEAD
pytest -q
```

完整阅读至少：

```text
iro_agent/gateway/feishu.py
iro_agent/cli.py
iro_agent/llm/glm_client.py
iro_agent/router/
iro_agent/investigation/harness.py
iro_agent/investigation/evidence_planner.py
iro_agent/investigation/hypotheses.py
iro_agent/investigation/evaluator.py
iro_agent/investigation/models.py
iro_agent/investigation/state.py
iro_agent/investigation/stop_conditions.py
iro_agent/investigation/trace.py
iro_agent/evaluation/runner.py
```

生成：

```text
docs/agentic_harness_baseline_260911.md
```

必须记录：

- HEAD SHA
- pytest baseline
- 当前 Feishu 执行链
- 当前 CLI 执行链
- 当前 Eval 执行链
- Runtime fault 是否真正进入 InvestigationHarness
- EvidencePlanner 当前如何生成候选步骤
- HypothesisManager 当前如何初始化假设
- 当前仍存在的 CaseType/关键词/fixed-step 规则

不要因为本计划中的函数名与当前 HEAD 有细小差异就另起炉灶；先映射现有代码，再做最小修改。

---

# 2. 目标架构

最终链路必须变成：

```text
                    User Message
                         │
                         ▼
                 RuntimeDispatcher
                         │
             ┌───────────┴───────────┐
             │                       │
             ▼                       ▼
        FACT_QUERY              RUNTIME_FAULT
             │                       │
             ▼                       ▼
     General Tool Agent       InvestigationHarness
                                     │
                                     ▼
                                LLM Planner
                                     │
                                     ▼
                           Structured Decision
                                     │
                                     ▼
                           Planner Validator
                                     │
                                     ▼
                            Read-only Tool
                                     │
                                     ▼
                                Evidence
                                     │
                                     ▼
                        Hypothesis State Update
                                     │
                                     ▼
                               Re-plan Loop
                                     │
                                     ▼
                              StopConditions
                                     │
                                     ▼
                               Final Report
```

关键原则：

> Harness 是 Controller；LLM 是 Planner；Tool 是 Executor；Evidence 是事实；Hypothesis 是可修改状态。

---

# 3. Phase 1 — 统一生产 Runtime

## 3.1 新增或完善 RuntimeDispatcher

优先复用现有 Router。如果没有统一入口，可新增：

```text
iro_agent/runtime/
├── __init__.py
├── dispatcher.py
└── models.py
```

核心接口：

```python
dispatch(message, context)
```

至少区分：

```text
FACT_QUERY
RUNTIME_FAULT
PROJECT_LEARNING
GENERAL_CHAT
```

其中本轮硬要求：

```text
RUNTIME_FAULT
→ InvestigationHarness.investigate(...)
```

不能再把 `investigation_pipeline` 仅作为 GLM 可选 Tool。

## 3.2 修改 Feishu

目标文件：

```text
iro_agent/gateway/feishu.py
```

禁止所有消息统一直接：

```python
glm_client.chat_completion(...)
```

应改为：

```python
runtime_dispatcher.dispatch(...)
```

对于 RUNTIME_FAULT：

```text
Feishu
→ RuntimeDispatcher
→ InvestigationHarness
→ Final Report
```

对于普通事实查询：

```text
Feishu
→ RuntimeDispatcher
→ General Tool Agent
```

## 3.3 修改 CLI

`iro-agent chat` 与飞书必须使用同一 RuntimeDispatcher。

可以额外提供：

```bash
iro-agent investigate "机器人不走"
```

用于显式调试，但普通 `chat` 遇到故障问题也必须自动路由。

## 3.4 验收

必须新增测试：

```text
tests/test_runtime_dispatcher_fault_route.py
tests/test_feishu_uses_runtime_dispatcher.py
tests/test_cli_uses_runtime_dispatcher.py
```

故障输入：

```text
机器人不动了，帮我查一下
```

必须断言：

```text
route == RUNTIME_FAULT
InvestigationHarness 被调用
General chat path 未被调用
```

普通输入：

```text
task 表有几个状态字段？
```

不得强制进入 Harness。

---

# 4. Phase 2 — 拆分 General Prompt 与 Investigation Planner Prompt

当前 `glm_client.py` 中如果存在：

```text
project_lookup → db_describe → db_query
```

以及固定故障排查顺序、固定 100 字输出等规则，必须拆分。

## 4.1 General Assistant Prompt

仅服务：

```text
FACT_QUERY / GENERAL_CHAT
```

可以保留：

- 不猜数据库字段
- schema 不确定时先 describe
- 工具只读
- 引用真实数据

但不再决定故障诊断路径。

## 4.2 Investigation Planner Prompt

新 Planner Prompt 只定义通用调查原则：

1. 用户描述是 reported symptom，不是 confirmed fact。
2. 建立多个可证伪的竞争假设。
3. 每轮只选择一个 Next Best Evidence。
4. 优先高可靠、低成本、能区分当前假设的证据。
5. 新证据可以支持、反驳、产生新假设。
6. 时序关系不等于因果关系。
7. Tool timeout/缺失等于 observability gap，不等于目标组件故障。
8. 数字证据未发现异常，不自动等于物理故障。
9. 证据充分时及时停止。
10. 证据不足时允许明确回答“不足以判断”。
11. 绝不执行写操作。

禁止写：

```text
PLC 问题固定先查 A 再查 B
Robot 问题固定查 heartbeat
P2C 出现必须查某日志
ERROR 出现就支持某根因
```

---

# 5. Phase 3 — 新增真正的 LLM Investigation Planner

推荐：

```text
iro_agent/investigation/llm_planner.py
```

定义稳定接口：

```python
class InvestigationPlanner:
    def plan(self, state, project_context, tools) -> PlannerDecision:
        ...
```

本轮直接复用现有 GLM Client，不增加模型供应商。

旧 EvidencePlanner 不立即删除，可改名或保留为：

```text
DeterministicEvidencePlanner
```

只用于：

- benchmark baseline
- regression helper
- 手工比较

生产默认必须：

```text
planner = llm
```

---

# 6. Planner 输入必须是当前状态，不是固定 CaseType 路线

每轮输入至少：

```json
{
  "symptom": "...",
  "project_context": {
    "architecture_summary": "...",
    "business_flow_summary": "...",
    "known_components": [],
    "source_of_truth_map": []
  },
  "hypotheses": [],
  "evidence": [],
  "failed_tools": [],
  "available_tools": [],
  "budget": {
    "remaining_iterations": 7,
    "remaining_tool_calls": 8
  }
}
```

不要把整个仓库一次性塞给 Planner。

项目知识不足时，`project_lookup` / `code_search` / `config_lookup` 本身也可以成为下一条 Evidence Tool。

---

# 7. Planner 输出必须是严格 JSON

建议 `PlannerDecision`：

```json
{
  "reasoning_summary": "当前需要区分后端未消费信号和信号未进入后端",
  "hypothesis_updates": [
    {
      "action": "add",
      "id": "H3",
      "statement": "PLC边界信号可能没有进入后端",
      "confidence": 0.34,
      "basis_evidence_ids": ["E1"]
    }
  ],
  "decision": {
    "action": "CALL_TOOL",
    "tool_name": "log_search",
    "arguments": {
      "keyword": "WAIT_P2C"
    },
    "expected_information": "判断后端是否持续等待P2C",
    "discriminates_hypotheses": ["H2", "H3"]
  },
  "stop": {
    "recommended": false,
    "reason": null
  }
}
```

只允许以下 action：

```text
CALL_TOOL
STOP_CONFIRMED
STOP_SUPPORTED
STOP_INSUFFICIENT_EVIDENCE
STOP_OBSERVABILITY_GAP
REQUEST_HUMAN_PHYSICAL_CHECK
```

不要让自然语言直接触发工具执行。

---

# 8. Phase 4 — PlannerValidator

Harness 必须验证 Planner，而不是盲信。

执行链：

```text
LLM Planner
→ JSON Schema
→ Tool whitelist
→ Read-only permission
→ Argument schema
→ Budget
→ Execute
```

以下必须拒绝：

```text
unknown tool
DB write
PLC write
Robot control
arbitrary shell
非法参数
超过预算
```

Planner JSON 错误允许 1 次 correction retry。

第二次仍错误：

```text
PLANNER_ERROR
```

不得偷偷 fallback 到旧固定流程然后正常 PASS。

---

# 9. Phase 5 — HypothesisManager 变成状态管理器

当前如果存在：

```text
PLC_SIGNAL_ERROR → 固定 H1~H4
ROBOT_ERROR → 固定 H1~H5
```

生产 Agentic 模式必须停止使用。

HypothesisManager 新职责：

```text
add
update
support
contradict
merge
retire
validate evidence references
normalize confidence
```

不负责提前提供“标准根因列表”。

第一轮 Hypothesis 由 LLM 根据：

```text
symptom
+ project blueprint
+ available tools
```

动态生成 2~5 个竞争假设。

要求：

- 可证伪。
- 不互为同义词。
- 有初始 confidence。
- confidence 只是 prior。
- 用户原话不是证据。

新 Evidence 之后允许：

```text
新增 Hypothesis
降低 confidence
提高 confidence
retire
merge
```

---

# 10. Phase 6 — EvidenceEvaluator 只负责“事实化”，不粗暴决定因果

如果当前存在类似：

```text
发现 ERROR
→ strongly_support(Hx)
```

必须收紧。

EvidenceEvaluator 负责：

```text
Tool output
→ normalize
→ provenance
→ source
→ timestamp
→ reliability
→ availability/error status
```

例如：

```text
PLC register = 0
heartbeat timestamp = current
SQL 0 rows
process not running
```

可以确定性解析为事实。

但：

```text
这条事实支持哪个根因
```

主要由 Planner 在下一轮结合完整状态判断。

必须明确区分：

```text
Evidence Fact
≠
Causal Conclusion
```

---

# 11. Phase 7 — 真正的逐轮 Re-plan

主循环必须接近：

```python
state = initialize_state(...)

while not deterministic_stop(state):

    decision = llm_planner.plan(
        state=state,
        project_context=...,
        tools=tool_registry.readonly_tools()
    )

    validated = planner_validator.validate(decision)

    apply_hypothesis_updates(validated)

    if validated.action == "CALL_TOOL":
        raw = tool_executor.execute(
            validated.tool_name,
            validated.arguments
        )

        evidence = evidence_normalizer.normalize(raw)
        state.add_evidence(evidence)

    trace.record(...)

    if validated.stop.recommended:
        stop_conditions.verify(...)
```

硬要求：

> 每获得一条新 Evidence 后，都重新调用 Planner。

禁止：

```text
LLM 一次规划十步
Python 顺序执行十步
```

---

# 12. Next Best Evidence 的要求

每轮 Planner 必须回答：

```text
为什么现在查这个？
它能区分哪些竞争 Hypothesis？
预期拿到什么信息？
```

不要求模型输出私有 Chain-of-Thought，只保留短的 `reasoning_summary` / decision rationale。

选择原则：

```text
高区分度
× 高可靠度
× 高相关性
÷ 获取成本
```

而不是固定：

```text
log → db → PLC → physical
```

“日志通常优先”只能作为 prior，不是死规则。

---

# 13. Phase 8 — StopConditions 继续确定性控制

不要把安全停止全部交给 LLM。

LLM 可以建议停止，Harness 最终校验。

至少保留：

```text
CONFIRMED_CAUSE
STRONG_CONVERGENCE
INSUFFICIENT_EVIDENCE
OBSERVABILITY_GAP
BUDGET_EXHAUSTED
REPEATED_NO_GAIN
PHYSICAL_ESCALATION
PLANNER_ERROR
```

## Confirmed

必须满足：

- Source-of-Truth 级直接事实，或
- 两条独立高质量证据共同支持。

强结论必须绑定 `evidence_id`。

## Supported

主要假设领先、有实质证据、无强反证。

输出措辞：

```text
“当前最可能”
```

不能写“已经确认”。

## Observability Gap

例如 PLC Reader timeout：

正确：

```text
PLC 状态当前不可观察
```

不是：

```text
PLC 异常
```

---

# 14. Phase 9 — Physical Escalation 继续是 Guardrail

不能：

```text
数字证据没找到
→ 自动检查硬件
```

只有：

```text
关键数字路径已经充分检查
+
数字证据不能解释现象
+
不存在重大 observability gap
```

才允许：

```text
REQUEST_HUMAN_PHYSICAL_CHECK
```

---

# 15. Phase 10 — ToolRegistry 必须成为唯一权限源

如果已有 Tool Registry，则完善；否则新增：

```text
iro_agent/investigation/tool_registry.py
```

每个工具包含：

```python
ToolSpec(
    name="log_search",
    readonly=True,
    category="log",
    cost=1,
    argument_schema=...
)
```

Planner 只能看到允许的只读工具。

严禁暴露：

```text
DB write
PLC write
Robot control
git write
shell arbitrary execute
```

---

# 16. Phase 11 — Production 与 Eval 必须走同一核心 Runtime

这是第二个 P0。

当前必须消除：

```text
Eval 直接测试 InvestigationHarness
生产飞书却走普通 GLM Tool Calling
```

最终：

```text
Production:
Feishu
→ RuntimeDispatcher
→ InvestigationHarness
→ LLM Planner

Eval:
Eval Case
→ RuntimeDispatcher
→ InvestigationHarness
→ LLM Planner
```

唯一差别：

```text
Production = real readers
Eval = fixture/mock readers
```

控制逻辑必须相同。

---

# 17. Phase 12 — 必须新增的关键测试

至少新增：

```text
tests/test_runtime_dispatcher_fault_route.py
tests/test_feishu_uses_runtime_dispatcher.py
tests/test_cli_uses_runtime_dispatcher.py

tests/test_llm_planner_schema.py
tests/test_llm_planner_tool_whitelist.py
tests/test_llm_planner_retry.py

tests/test_dynamic_hypothesis_creation.py
tests/test_dynamic_hypothesis_retirement.py
tests/test_new_evidence_changes_next_tool.py
tests/test_same_symptom_different_evidence_different_path.py

tests/test_unknown_fault_agentic_planning.py
tests/test_planner_no_case_hardcoding.py
tests/test_tool_timeout_is_observability_gap.py

tests/test_end_to_end_runtime_eval.py
```

---

# 18. 必须通过的行为测试

## T1：生产故障进入 Harness

输入：

```text
机器人不动了，帮我查一下
```

必须：

```text
route == RUNTIME_FAULT
InvestigationHarness called
General Chat path not called
```

## T2：普通事实查询不进入 Harness

输入：

```text
task 表一共有几个状态字段？
```

走 General Tool Agent。

## T3：同一个症状，不同证据走不同路线

症状：

```text
机器人不走
```

Scenario A：

```text
backend WAIT_P2C
```

下一步偏 PLC/boundary。

Scenario B：

```text
task created + robot dispatch timeout
```

下一步偏 Robot heartbeat/API。

必须证明：

```text
same symptom != fixed route
```

## T4：没有 CaseType 的新故障也能排查

输入：

```text
Kiosk显示送餐中，但是后台任务已经完成，机器人停在转角点。
```

源码中不得先新增 `KIOSK_ERROR` 固定模板。

Planner 必须能：

- 生成 Hypothesis
- 选择 Tool
- 根据 Evidence 改路线
- 最终停止

## T5：新证据可以创造新假设

初始：

```text
H1 PLC
H2 Backend
H3 Robot
```

后来发现：

```text
timestamp drift 20 min
```

允许新增：

```text
H4 stale evidence / system clock
```

## T6：反证淘汰假设

已有：

```text
H_robot_connection = 0.42
```

新证据：

```text
heartbeat current
callback current
robot online
```

必须显著降低或 retire。

## T7：非法工具被拒绝

Planner 试图：

```text
robot_control
```

必须 BLOCK，且不执行。

## T8：Planner 两次输出非法 JSON

结果：

```text
PLANNER_ERROR
```

不能旧流程 fallback。

## T9：工具 timeout

PLC Reader timeout：

```text
OBSERVABILITY_GAP
```

不能成为“PLC故障证据”。

## T10：证据充分后及时停止

已有：

```text
backend WAIT_P2C
+
actual P2C=0
```

如果已满足强收敛，不应继续无关 Robot/physical 排查。

---

# 19. Phase 13 — Trace 必须能解释行为

每轮至少保存：

```json
{
  "round": 2,
  "hypotheses_before": [],
  "evidence_before": [],
  "planner_decision": {},
  "selected_tool": "log_search",
  "selection_reason": "用于区分 H1/H2",
  "expected_information": "...",
  "tool_result_summary": "...",
  "normalized_evidence": {},
  "hypothesis_updates": [],
  "stop_decision": {}
}
```

现场发现异常行为后必须能回答：

```text
为什么查 A？
A 返回后为什么改查 C？
为什么放弃 B？
哪个 Evidence 导致 H2 降低？
为什么停止？
```

---

# 20. Phase 14 — 旧 Deterministic Planner 的处理

不直接删除。

明确标记：

```text
legacy / benchmark / deterministic baseline
```

生产默认：

```json
{
  "investigation": {
    "planner": "llm"
  }
}
```

Eval 默认也使用：

```text
planner=llm
```

生产 LLM Planner 不可用时，不建议自动 fallback。

正确：

```text
PLANNER_ERROR / diagnosis unavailable
```

或明确：

```text
LIMITED_DIAGNOSTIC_MODE
```

绝不能静默 fallback 后让用户以为 Agentic Harness 正常运行。

---

# 21. Phase 15 — 防止自主 Agent 乱逛

Agentic 不等于无限自由。

继续硬限制：

```text
max_iterations = 10
max_tool_calls = 12
max_no_gain_rounds = 2
max_repeat_same_query = 1~2
```

连续两轮：

```text
无新增 Evidence
无明显 Hypothesis 更新
无信息增益
```

应：

```text
STOP_INSUFFICIENT_EVIDENCE
```

---

# 22. Phase 16 — 输出格式与调查策略彻底分离

可以保留用户输出格式：

```text
结论
关键依据
未确认项
下一步
```

但不要再把：

```text
100字
```

和固定排查路线绑在一起。

建议：

```text
brief
normal
debug
```

飞书默认 normal 或 brief。

注意：

```text
presentation template != investigation policy
```

---

# 23. Phase 17 — Evaluation 新增 Agentic 指标

在现有指标上增加：

```text
Agentic Route Rate
Dynamic Replan Rate
Hypothesis Revision Rate
Fixed-Path Violation Rate
Planner Error Rate
Invalid Tool Attempt Rate
No-Gain Stop Rate
Runtime/Eval Path Consistency
```

尤其增加：

## Fixed-Path Violation

准备：

```text
相同 symptom
不同 evidence
```

如果总是：

```text
Tool A → Tool B → Tool C
```

判定：

```text
Fixed-Path Suspected
```

---

# 24. 禁止“失败一个 case 就新增一个规则”

错误做法：

```text
Kiosk case 失败
→ 新增 KIOSK_ERROR
→ 写固定 Kiosk steps
```

正确做法：

```text
检查 Planner 为什么没形成正确 Hypothesis
检查 Tool Catalog 是否缺失
检查 Blueprint 是否缺失关键项目知识
检查 Evidence 是否没有被正确规范化
检查 stop/replan 是否错误
```

CaseType 可以继续存在，用于：

```text
metric grouping / reporting
```

但不能主导生产 next step。

---

# 25. 推荐 Commit 顺序

## Commit 1

```text
chore: capture agentic harness runtime baseline
```

- baseline doc
- pytest baseline
- 三条执行链图

## Commit 2

```text
refactor(runtime): route production fault queries through investigation harness
```

- RuntimeDispatcher
- Feishu
- CLI
- tests

这是本轮最优先提交。

## Commit 3

```text
feat(investigation): add structured llm investigation planner
```

- Planner interface
- PlannerDecision schema
- GLM implementation
- validation/retry

## Commit 4

```text
refactor(investigation): make hypotheses dynamically generated and revisable
```

- HypothesisManager 状态化
- initial hypotheses from LLM
- add/update/retire/merge

## Commit 5

```text
refactor(investigation): replace fixed candidate routes with per-round replanning
```

- production 不再使用 CaseType 固定候选步骤
- 每轮 Planner
- same-symptom/different-evidence tests

## Commit 6

```text
refactor(investigation): separate evidence facts from causal judgment
```

- 收紧 EvidenceEvaluator
- observability gap
- timeout semantics

## Commit 7

```text
test(eval): align production and evaluation runtime paths
```

- Eval 走 RuntimeDispatcher
- End-to-End Eval
- Runtime/Eval consistency

## Commit 8

```text
docs: document agentic investigation runtime and trace semantics
```

- README
- architecture
- config
- debug方法

---

# 26. 每个 Commit 的验收方式

每个 commit 后：

```bash
pytest -q
iro-agent eval dev
iro-agent eval regression
```

另外人工执行至少：

```text
1 个 PLC 问题
1 个 Robot 问题
1 个 DB/状态问题
1 个源码里没有固定模板的新问题
```

记录 trajectory。

Critical Regression 失败不得进入下一 commit。

---

# 27. 源码级检查

完成后搜索：

```bash
grep -R "PLC_SIGNAL_ERROR" iro_agent/investigation
grep -R "ROBOT_EXECUTION_ERROR" iro_agent/investigation
grep -R "P2C" iro_agent/investigation
```

如果仍发现：

```text
CaseType → 固定排查步骤
关键词 → 固定 next tool
```

作为生产主路径，则本轮未完成。

允许这些词存在于：

```text
tests
metrics grouping
legacy baseline
documentation
```

但不能决定 Agentic Planner 的核心行为。

---

# 28. Definition of Done

## Runtime

- [ ] Feishu 故障问题强制进入 InvestigationHarness
- [ ] CLI 与 Feishu 共用 RuntimeDispatcher
- [ ] 普通事实问题保留轻量工具路径
- [ ] Eval 与生产共用同一 Harness 控制逻辑

## Planner

- [ ] 每轮新 Evidence 后重新调用 LLM Planner
- [ ] Planner 返回严格 JSON
- [ ] Harness 校验 Tool/参数/权限/预算
- [ ] 非法 Planner 输出不执行
- [ ] Planner 失败不静默 fallback

## Hypothesis

- [ ] 初始假设不是固定 CaseType 模板
- [ ] 可以新增
- [ ] 可以降低
- [ ] 可以 retire
- [ ] 可以 merge
- [ ] 每个强判断绑定 Evidence
- [ ] 用户描述不是 confirmed evidence

## Evidence

- [ ] Evidence Fact 与 Causal Conclusion 分离
- [ ] ERROR 不自动等于根因
- [ ] timeout = observability gap
- [ ] 时序不自动等于因果
- [ ] provenance 完整

## Replanning

- [ ] 同一症状不同 Evidence 能走不同路线
- [ ] 新 Evidence 会改变 next tool
- [ ] 未预设 CaseType 的故障仍能调查
- [ ] 不存在生产固定 Tool A→B→C 主流程

## Safety

- [ ] DB write = 0
- [ ] PLC write = 0
- [ ] Robot control = 0
- [ ] arbitrary shell = 0
- [ ] forbidden tool 被 Harness 阻止

## Stop

- [ ] 证据充分及时停
- [ ] 证据不足敢停
- [ ] Observability Gap 不误判
- [ ] Physical Escalation 受 Guardrail 约束
- [ ] no-gain 会停止

---

# 29. 最终交付文档

完成后生成：

```text
docs/agentic_harness_result_260911.md
```

至少包含：

1. 修改前生产执行链
2. 修改后生产执行链
3. 实际 Commit 清单
4. 关键文件变更
5. PlannerDecision schema
6. Hypothesis lifecycle
7. Tool safety model
8. Feishu / CLI / Eval 是否共用 Runtime
9. 新增测试
10. DEV / Regression 前后结果
11. 至少 4 个现场测试 trajectory
12. 所有仍保留的 deterministic 规则
13. 所有仍存在的 CaseType-specific / keyword-specific / fixed-step 逻辑
14. 每一项保留理由
15. 当前仍未解决的问题

---

# 30. 给本地 Coding AI 的最终指令

严格遵守：

> 不要继续往 EvidencePlanner 里堆 if/else。  
> 不要通过增加更多 CaseType 模板来伪装“支持更多故障”。  
> 不要推倒现有 Safety、Evidence、Evaluation 基础设施。  
> 第一优先级是让 Feishu、CLI、Eval 的故障诊断真正使用同一个 InvestigationHarness。  
> 第二优先级是让 LLM 在每一轮根据最新 InvestigationState 动态生成/修改 Hypothesis，并只决定一个 Next Best Evidence。  
> Harness 负责权限、安全、结构校验、工具执行、Evidence 记录、预算和停止；不要替 LLM 预设具体故障路线。

最终是否完成，不看“有没有新增 LLMPlanner 类”，而看：

> **面对一个源码中从未专门预设排查路线的新故障，IRO_agent 能否利用 Project Knowledge + 当前 Evidence 自主形成竞争假设、选择下一证据、根据新证据改变路线，并在证据充分或不足时正确停止。**

只有做到这一点，才算真正从 Deterministic Investigation Harness 升级为 Agentic Investigation Harness。
