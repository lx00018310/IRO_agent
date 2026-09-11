# IRO_agent V0.5 — True Deep Bootstrap & Investigation Harness Plan

## 1. Goal

Upgrade IRO_agent in two major directions:

1. **True Deep Project Bootstrap**
   - replace the current mostly-static pseudo multi-pass bootstrap with real multi-round GLM-5.3-Flash structured learning
   - make initialization genuinely learn project architecture, module responsibilities, config systems, code paths, business flows, interfaces, database semantics, and unknown areas

2. **Investigation Harness**
   - add a deterministic diagnostic strategy layer above the existing readers/tools
   - make troubleshooting follow an evidence-priority process instead of unrestricted LLM tool calling
   - use hypothesis-driven investigation with explicit stop conditions

The first validation project remains **TASK-013**.

---

## 2. Core Product Direction

```text
Question
  |
  v
Intent + Project Knowledge
  |
  v
Investigation Harness
  |
  v
Hypotheses
  |
  v
Evidence Plan
  |
  v
Tool Execution
  |
  v
Evidence Evaluation
  |
  v
Hypothesis Update
  |
  +-> continue
  |
  +-> stop
  |
  v
Final Explanation
```

---

# PART A — TRUE DEEP PROJECT BOOTSTRAP

## 3. Current Problem

The current bootstrap presents multiple passes, but most logic is implemented through deterministic Python heuristics.

The desired behavior is:

```text
static scanners
   ->
structured evidence
   ->
multiple real GLM calls
   ->
deep-read requests
   ->
more evidence
   ->
structured synthesis
   ->
critic pass
   ->
validated project knowledge
```

Initialization must not silently succeed in deep mode without actual GLM calls.

## 4. Required Bootstrap Modes

Default:

```text
iro-agent init
```

must perform deep bootstrap.

Optional debug mode:

```text
iro-agent init --static-only
```

may retain static-only behavior.

## 5. Bootstrap Stage Overview

```text
Stage 0 — Static Evidence Collection
Stage 1 — System Architecture Learning
Stage 2 — Module Deep Learning
Stage 3 — Configuration System Learning
Stage 4 — Database / State / Persistence Learning
Stage 5 — Business Flow Learning
Stage 6 — Interface / PLC / Robot / External System Learning
Stage 7 — Cross-Validation / Critic Pass
Stage 8 — Knowledge Validation
Stage 9 — Persist + Report
```

Every GLM stage must create an actual model call when relevant evidence exists.

## 6. Stage 0 — Static Evidence Collection

Reuse existing scanners and collect:

```text
project tree
technology stack
code graph
controllers
services
mappers/repositories
entities/models
SQL/table usage
config files
database schema
enums/states
version-provider information
frontend API usage
external endpoint references
```

Output a structured `BootstrapEvidenceBundle`.

## 7. Bootstrap Evidence Bundle

Recommended structure:

```text
BootstrapEvidenceBundle
├─ project_tree
├─ tech_stack
├─ modules
├─ code_entities
├─ code_relationships
├─ database_schema
├─ config_files
├─ config_keys
├─ states
├─ apis
├─ external_endpoints
└─ known_unknowns
```

Keep evidence references such as file, line, table, field, config file and symbol.

## 8. Stage 1 — System Architecture Learning

Perform a real GLM call using:

```text
project tree
tech stack
startup scripts
major modules
top-level code relationships
major configs
```

Return structured JSON containing:

```text
project purpose
major runtime components
module responsibilities
startup/runtime architecture
important data paths
important unknown areas
which modules require deep reading
```

Persist:

```text
project_overview
architecture_map
deep_read_targets
```

## 9. Stage 2 — Module Deep Learning

For each important module selected in Stage 1:

1. select the most relevant files
2. read actual code content
3. include code graph relationships
4. call GLM
5. persist structured module knowledge

Recommended module data:

```text
module_name
business_role
technical_role
entry_points
important_classes
important_services
important_tables
important_configs
state_transitions
external_dependencies
known_unknowns
confidence
evidence
```

## 10. File Selection Strategy

Prioritize:

```text
entry points
controllers
services
mappers/repositories
state machines
config loaders
device integration code
core schedulers
critical business classes
```

Deprioritize:

```text
generated files
DTO-only files
tests
boilerplate
static assets
```

Add configurable limits:

```text
max_modules
max_files_per_module
max_lines_per_file
max_total_deep_read_lines
```

## 11. Stage 3 — Configuration System Learning

Inputs:

```text
ConfigCatalog
config loader code
environment-variable references
external config path logic
project config
ProgramData/external config references
defaults
```

Perform a real GLM call and persist:

```text
config_files
config_keys
config_meanings
config_precedence
config_load_paths
runtime_external_config_locations
read_by
known_unknowns
```

Where possible, map:

```text
config key
  ->
reader code
  ->
business usage
```

## 12. Stage 4 — Database / State / Persistence Learning

Inputs:

```text
runtime DB schema
entities
mappers/repositories
SQL
service usage
status fields
enums
```

Perform a real GLM call and persist:

```text
table roles
current-state tables
history tables
callback tables
audit tables
source-of-truth candidates
state fields
state transitions
write paths
read paths
known_unknowns
```

Do not mark table semantics `confirmed` from names alone.

## 13. Stage 5 — Business Flow Learning

Discover candidate business flows from:

```text
APIs
services
frontend labels
states
tables
logs terminology
config keys
external integrations
```

For each top flow:

1. gather related code chain
2. gather related tables/configs
3. gather related interfaces
4. call GLM
5. persist a structured `BusinessFlow`

Recommended structure:

```text
flow_id
name
aliases
entry_points
steps
controllers
services
mappers
tables
configs
states
external_systems
runtime_evidence_sources
source_of_truth
unknown_steps
confidence
evidence
```

## 14. Stage 6 — Interface / Device / External System Learning

Learn:

```text
HTTP APIs
callback protocols
PLC integration
robot integration
Android bridge
socket/TCP interfaces
file-based interfaces
third-party services
```

Persist:

```text
system/interface name
direction
producer
consumer
protocol
key states/signals
config
logs
related code
failure indicators
known_unknowns
```

This knowledge must later be usable by InvestigationHarness.

## 15. Stage 7 — Critic Pass

Run a separate GLM pass that asks:

```text
Which conclusions lack evidence?
Which modules were insufficiently read?
Which business flows contain gaps?
Which source-of-truth rules are only inferred?
Which interfaces are unclear?
Which config precedence rules are uncertain?
```

Output:

```text
confirmed_facts
strongly_inferred_facts
weak_inferences
unknown_areas
contradictions
recommended_followup_reads
```

If budget allows, perform one targeted follow-up deep-read round.

## 16. Stage 8 — Validation

Programmatically validate:

```text
files exist
symbols exist
tables exist
fields exist
config files exist
config keys exist
API paths exist
code relationships exist
referenced modules exist
```

Allowed confidence:

```text
CONFIRMED
STRONGLY_SUPPORTED
SUPPORTED
INFERRED
UNKNOWN
```

Downgrade unsupported claims.

## 17. Stage 9 — Persist + Bootstrap Report

Persist to Project Knowledge and generate a report such as:

```text
Deep Bootstrap Report

GLM calls: 16
Files deeply read: 43
Lines inspected: 8,720

Modules:
  Backend           STRONGLY_SUPPORTED
  Frontend          STRONGLY_SUPPORTED
  PLC Integration   SUPPORTED
  Robot Integration SUPPORTED

Business Flows:
  Material Call     COMPLETE
  Dispatch          COMPLETE
  Callback          PARTIAL
  Cancel            PARTIAL

Knowledge:
  Confirmed facts: 146
  Strongly supported: 61
  Inferred: 29
  Unknown: 18

Unknown Areas:
  PLC register mapping
  robot internal safety state
```

## 18. Bootstrap Observability

During bootstrap print real progress:

```text
[Bootstrap 1/9] Static evidence collection...
[Bootstrap 2/9] GLM architecture learning...
[Bootstrap 3/9] Deep-reading backend module...
[Bootstrap 4/9] Learning configuration system...
...
```

Also show:

```text
GLM call count
deep-read files
token usage if available
elapsed time
```

---

# PART B — INVESTIGATION HARNESS

## 19. Purpose

Create:

```text
InvestigationHarness
```

Its responsibility is not to answer the question. Its responsibility is:

> Decide how to investigate, in what order, using which evidence, and when to stop.

## 20. Runtime Position

```text
IntentRouter
    |
    v
InvestigationHarness
    |
    v
HypothesisManager
    |
    v
EvidencePlanner
    |
    v
ToolExecutor
    |
    v
EvidenceEvaluator
    |
    v
Hypothesis Update
    |
    +-> Next Step
    |
    +-> Stop
    |
    v
Final Answer
```

## 21. Evidence Priority Tiers

### Tier 1A — Runtime Digital Facts

Highest default priority:

```text
logs
runtime database state
active/effective configuration
active version/release information
```

These answer: **What actually happened?**

### Tier 1B — Static System Facts

Very high priority:

```text
code
state machine
business flow
config loading logic
protocol definitions
```

These answer: **What should happen?**

### Tier 2 — System Boundary Evidence

Examples:

```text
API request/response
callback
PLC state/register
robot state
Android bridge
heartbeat
network connection
protocol frames
```

These answer: **At which system boundary did expected state stop propagating?**

### Tier 3 — Runtime Environment

Examples:

```text
process
Windows service
port
CPU
memory
disk
thread
connection pool
DNS
filesystem permission
network interface
```

### Tier 4 — Physical / Out-of-Band

Examples:

```text
power
wiring
sensor
E-stop
mechanical jam
actual robot position
actual PLC input light
manual intervention
human operation
```

IRO_agent usually cannot directly verify these. At this tier it should generate a physical inspection checklist instead of pretending to know the cause.

## 22. Dynamic Priority Rule

Evidence tiers are defaults, not a rigid order.

Actual ordering should use:

```text
Default Evidence Priority
+
Problem Relevance
+
Expected Information Gain
+
Evidence Cost
=
Investigation Order
```

Example:

```text
PLC已经发P2C，为什么机器人不走？
```

PLC/robot boundary evidence should move ahead of general code review.

## 23. Investigation Case Types

Initial categories:

```text
APPLICATION_ERROR
DATA_STATE_ERROR
CONFIGURATION_ERROR
VERSION_CHANGE_ERROR
INTERFACE_COMMUNICATION_ERROR
PLC_SIGNAL_ERROR
ROBOT_EXECUTION_ERROR
NETWORK_ENVIRONMENT_ERROR
UNKNOWN_RUNTIME_FAULT
```

Classification may be multi-label.

## 24. Default Investigation Paths

### A. Application / Backend Error

```text
1. logs
2. runtime DB state
3. active config
4. related code/state machine
5. API/interface
6. runtime environment
7. physical/out-of-band if relevant
```

### B. Data / State Error

```text
1. runtime DB
2. logs
3. source-of-truth/project knowledge
4. code/state transitions
5. upstream/downstream interface
6. runtime environment
```

### C. Configuration Error

```text
1. effective config
2. config precedence
3. learning memory
4. config reader code
5. logs
6. external environment/config source
```

### D. Interface / Callback Error

```text
1. sender log
2. receiver log
3. request/response/callback record
4. protocol/config
5. network/connectivity
6. code
7. runtime environment
```

### E. PLC Signal Error

```text
1. PLC state/register evidence
2. backend PLC communication log
3. related business state
4. PLC config/protocol mapping
5. backend code
6. network
7. physical sensor/wiring
```

### F. Robot Execution Error

```text
1. backend dispatch/task evidence
2. robot/API response
3. robot/bridge state
4. related logs
5. state machine/code
6. PLC/safety conditions
7. network/runtime environment
8. physical robot/safety/mechanical checks
```

### G. Network / Environment Error

```text
1. connection/log evidence
2. process/service
3. port/network state
4. CPU/memory/disk
5. DNS/filesystem
6. code/config only if relevant
```

## 25. Hypothesis Generation

For runtime faults, generate 2–6 hypotheses.

Example:

```text
Problem:
机器人未执行送餐

H1 backend没有创建任务
H2 backend创建任务但发送Robot API失败
H3 robot收到任务但未执行
H4 PLC/safety条件阻止执行
H5 physical/mechanical issue
```

Each hypothesis contains:

```text
hypothesis_id
description
related_flow_step
required_evidence
supporting_evidence
contradicting_evidence
status
confidence
```

## 26. Hypothesis Status

Use:

```text
CONFIRMED
STRONGLY_SUPPORTED
SUPPORTED
UNRESOLVED
WEAK
RULED_OUT
```

Avoid fake precision percentages by default.

## 27. Evidence Planner

For each hypothesis define:

```text
which evidence can support it
which evidence can rule it out
which tool retrieves that evidence
evidence tier
cost
expected information gain
```

Example:

```text
H1: backend没有创建任务

Evidence:
- DB task row
- backend task-creation log

If DB row exists + creation log exists:
RULED_OUT
```

## 28. Investigation Step Model

```text
step_id
hypothesis_ids
evidence_type
tool
query
reason
priority
result
evaluation
```

Persist investigation trace internally for debugging.

## 29. Evidence Evaluation

Normalize tool results into:

```text
FACT
SUPPORTING
CONTRADICTING
INCONCLUSIVE
MISSING
```

Example:

```text
DB task exists
-> contradicts "task not created"
```

## 30. Stop Conditions

Stop when one of the following is true.

### Strong conclusion

```text
one hypothesis is strongly supported
+
at least two independent high-quality evidence items
+
no major contradiction
```

### Confirmed conclusion

```text
direct runtime evidence identifies root cause
```

### Insufficient digital evidence

```text
all relevant digital tiers exhausted
+
no supported hypothesis
```

Then escalate to physical/out-of-band checks.

## 31. Do Not Over-Investigate

Once a sufficient conclusion exists, do not continue querying unrelated lower-priority layers.

Example:

```text
DB connection timeout
+
DB connectivity failure
```

should not trigger PLC/robot investigation.

## 32. Physical Escalation

When digital evidence is insufficient:

```text
do not invent a software cause
```

Return:

```text
Digital evidence exhausted.
Next physical checks:
1. ...
2. ...
3. ...
```

Use Project Knowledge to make the checklist project-specific where possible.

## 33. Project Knowledge Integration

InvestigationHarness must use:

```text
BusinessFlow
ConfigCatalog
SourceOfTruth
InterfaceMap
CodeGraph
LearningMemory
IncidentMemory
```

Example:

```text
Material Call Flow:
WMS -> Backend -> Dock Task -> PLC -> Robot
```

The harness should investigate along this flow rather than across the whole system.

## 34. Learning Memory Integration

Before planning:

```text
learning_recall(question)
```

Learned rules must affect investigation behavior.

## 35. Incident Memory Integration

Historical incidents may seed hypotheses but must not count as proof of the current root cause.

## 36. Investigation Plan Visibility

In CLI/debug mode, optionally show a compact structured plan:

```text
[Investigation Plan]

Likely flow:
Material Call -> Dock Task -> PLC -> Robot

Hypotheses:
H1 task not created
H2 robot command not sent
H3 robot rejected command
H4 safety/physical block

Initial evidence order:
1. backend log
2. dock task DB
3. robot API/bridge state
4. PLC safety state
```

Do not expose hidden chain-of-thought. Show only structured plan/results.

## 37. Tool Access Strategy

For runtime faults, prefer:

```text
Harness selects tool
GLM helps formulate query and interpret evidence
```

over unrestricted free-form GLM tool choice.

## 38. Existing DiagnosticOrchestrator

Do not delete it immediately.

Refactor it into a lower-level evidence collector/helper where useful.

`InvestigationHarness` becomes the top-level runtime fault coordinator.

---

# PART C — VALIDATION

## 39. Deep Bootstrap Validation

Run:

```text
iro-agent init --refresh
```

Expected:

- multiple real GLM calls
- visible stage progress
- deep-read file count > 0
- business-flow knowledge > 0
- interface/device knowledge > 0
- critic report present
- unknown areas explicitly listed

## 40. Bootstrap Mock Test

Mock GLM and assert these passes really call the model:

```text
architecture pass
module pass
config pass
DB/state pass
business-flow pass
external-system pass
critic pass
```

A test must fail if `GlmClient` is constructed but never invoked.

## 41. Investigation Validation — Backend Failure

Known backend exception case.

Expected path approximately:

```text
logs
DB/config/code
```

Do not query PLC/robot if backend cause is already strongly supported.

## 42. Investigation Validation — PLC Problem

Known PLC signal/communication case.

Expected:

```text
PLC evidence promoted
backend PLC logs
related business state
protocol/config
physical checks only if unresolved
```

## 43. Investigation Validation — Robot Not Moving

Expected hypotheses include:

```text
task not created
robot command not sent
robot response failure
safety/PLC block
physical issue
```

The harness should narrow hypotheses instead of querying everything.

## 44. Investigation Validation — No Digital Cause

Synthetic case where all digital evidence appears normal.

Expected final result:

```text
No supported digital root cause.
Physical/out-of-band inspection required.
```

Must not fabricate a software bug.

## 45. Investigation Validation — Known Config Issue

Expected:

```text
Learning Memory
-> ConfigCatalog
-> effective config
```

before generic code search.

## 46. Required Tests

Add:

```text
test_deep_bootstrap_glm_calls.py
test_deep_bootstrap_critic.py
test_bootstrap_report.py

test_investigation_harness.py
test_hypothesis_manager.py
test_evidence_planner.py
test_dynamic_priority.py
test_stop_conditions.py
test_physical_escalation.py
```

## 47. Regression Requirements

Must preserve:

```text
read-only security
Project Knowledge
Learning Memory
Incident Memory
VersionReader
DBReader
LogReader
CodeReader/CodeGraph
Feishu Gateway
Secret Redaction
```

No write capability may be introduced.

---

# PART D — IMPLEMENTATION

## 48. Suggested File Structure

```text
iro_agent/
├─ investigation/
│  ├─ __init__.py
│  ├─ harness.py
│  ├─ models.py
│  ├─ classifier.py
│  ├─ hypotheses.py
│  ├─ evidence_planner.py
│  ├─ evaluator.py
│  ├─ priorities.py
│  └─ stop_conditions.py
│
├─ knowledge/
│  ├─ bootstrap.py
│  ├─ synthesizer.py
│  ├─ deep_reader.py
│  └─ bootstrap_report.py
```

Adapt to current repository where cleaner.

## 49. Development Phases

### Phase 1
Make every Deep Bootstrap pass perform real GLM calls.

### Phase 2
Add module deep-read selection.

### Phase 3
Add business-flow deep synthesis.

### Phase 4
Add interface/device deep synthesis.

### Phase 5
Add critic pass and Bootstrap Report.

### Phase 6
Define investigation evidence tiers and case types.

### Phase 7
Implement HypothesisManager.

### Phase 8
Implement EvidencePlanner and dynamic priority.

### Phase 9
Implement EvidenceEvaluator.

### Phase 10
Implement stop conditions.

### Phase 11
Implement physical escalation.

### Phase 12
Integrate Project/Learning/Incident knowledge.

### Phase 13
Route runtime faults through InvestigationHarness.

### Phase 14
Run TASK-013 real validation cases.

## 50. Recommended Commit Sequence

```text
01 fix: make deep bootstrap passes invoke glm
02 feat: add targeted module deep reader
03 feat: add deep config and database synthesis
04 feat: add business flow glm synthesis
05 feat: add interface and external system synthesis
06 feat: add bootstrap critic pass
07 feat: add bootstrap quality report

08 feat: add investigation harness models
09 feat: add investigation case classifier
10 feat: add hypothesis manager
11 feat: add evidence priority tiers
12 feat: add evidence planner
13 feat: add evidence evaluator
14 feat: add dynamic investigation ordering
15 feat: add stop conditions
16 feat: add physical escalation
17 refactor: route runtime faults through investigation harness
18 test: add deep bootstrap glm-call verification
19 test: add task013 investigation-path cases
20 docs: document investigation strategy
```

## 51. Definition of Done

V0.5 is complete when:

- Deep Bootstrap performs actual multiple GLM calls.
- Bootstrap cannot silently succeed without invoking GLM in deep mode.
- Core modules are deep-read.
- Config semantics are learned through GLM.
- Database/state semantics are learned through GLM.
- Business flows are synthesized.
- PLC/robot/external-system relationships are synthesized.
- Critic pass identifies unsupported/unknown areas.
- Bootstrap report shows real depth and coverage.
- Runtime faults use InvestigationHarness.
- InvestigationHarness creates hypotheses.
- Evidence is prioritized dynamically.
- High-confidence digital evidence is checked first.
- Irrelevant lower layers are skipped when a strong cause is already found.
- PLC/robot/interface evidence can be promoted when the problem indicates it.
- Physical-layer checks occur only after digital investigation is insufficient.
- Unknown remains unknown.
- Existing read-only guarantees remain intact.

## 52. Final Design Principle

Deep Bootstrap answers:

> **How does this project actually work?**

InvestigationHarness answers:

> **Given this symptom, what is the highest-value evidence to inspect next?**

Together they should make IRO_agent behave less like a general LLM with tools and more like an experienced industrial resident engineer performing disciplined troubleshooting.
