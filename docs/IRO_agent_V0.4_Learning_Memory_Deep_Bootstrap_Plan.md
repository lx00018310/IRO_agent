# IRO_agent V0.4 — Durable Learning Memory & Deep Project Bootstrap Plan

## 1. Goal

Upgrade IRO_agent in two focused directions:

1. **Durable Learning Memory**
   - persist user corrections and operational rules
   - retrieve them in future related questions
   - only claim "remembered" after persistence succeeds

2. **Deep Project Bootstrap**
   - upgrade `iro-agent init` from shallow project summarization into structured multi-stage project learning
   - build durable knowledge about modules, configuration, business flows, code relationships, database semantics, and operational rules

The first validation target remains **TASK-013**.

## 2. Final Knowledge Architecture

IRO_agent must maintain five distinct knowledge layers:

```text
1. Project Knowledge
   What this system is

2. Runtime Evidence
   What is happening now

3. Incident Memory
   What failures happened before

4. Conversation Memory
   What we are discussing in this session

5. Learning Memory
   What users have corrected or taught the agent
```

These layers must not be mixed.

## 3. Core Runtime Model

```text
User Question
    |
    v
Intent Router
    |
    +-> Project Knowledge
    +-> Learning Memory
    +-> Incident Memory
    |
    v
Investigation Plan
    |
    +-> Config
    +-> DB
    +-> Code
    +-> Logs
    +-> Version
    |
    v
Runtime Evidence
    |
    v
GLM
    |
    v
Answer
```

## 4. Scope

Included:

- durable correction memory
- learning recall
- correction detection
- persistent operational rules
- multi-stage project bootstrap
- project map
- module-level deep reading
- config catalog
- business flow knowledge
- project knowledge persistence
- query-time routing to config/project/code knowledge
- bootstrap freshness/refresh
- TASK-013 validation

Excluded:

```text
new Feishu features
new Gateway types
GUI
EXE
automatic code modification
automatic remediation
vector database
Milvus
Elasticsearch
new dashboards
write access to production systems
```

# PART A — DURABLE LEARNING MEMORY

## 5. Problem

The agent must not say:

```text
"已记住该原则"
```

when the information exists only in temporary conversation history.

Example:

```text
查询配置应该遍历所有配置文件目录中的所有配置文件，
而不仅仅使用 grep 检索。
```

This must survive CLI restart, Gateway restart, machine restart, and new sessions.

## 6. LearningMemoryStore

Create:

```text
LearningMemoryStore
```

Recommended storage: SQLite.

Suggested table:

```text
learning_rules
```

Minimum fields:

```text
rule_id
project
rule_type
topic
rule_text
reason
source_type
source_message_id
confidence
created_at
updated_at
last_used_at
use_count
status
```

Recommended `rule_type` values:

```text
operation_rule
source_of_truth_correction
configuration_rule
business_semantic_correction
tool_usage_rule
terminology_mapping
other
```

Recommended `source_type`:

```text
user_correction
manual_override
validated_system_learning
```

## 7. Example Learning Rule

```json
{
  "project": "TASK-013",
  "rule_type": "configuration_rule",
  "topic": "configuration_lookup",
  "rule_text": "查询配置时必须遍历允许读取的配置目录及其中所有配置文件，不能仅依赖代码 grep。",
  "reason": "ordersys-settings.json 曾因只做 grep 而被漏检",
  "source_type": "user_correction",
  "confidence": "confirmed"
}
```

## 8. Learning Tools

Add internal-memory tools:

```text
learning_recall(query)
learning_save(rule)
learning_list(topic=None)
```

Optional:

```text
learning_deactivate(rule_id)
```

These tools may write only to IRO_agent's own memory.

## 9. Memory Honesty Rule

IRO_agent may only say "已记住", "我会记住", or equivalent after `learning_save()` succeeds.

If persistence fails, explicitly report that the rule was not saved.

## 10. Correction Detection

Recognize phrases such as:

```text
不是这个，是...
你查错了...
正确的是...
以后应该...
记住...
这里要以...为准
这个表不是用来...的
这个配置在...
正确做法是...
```

Flow:

```text
User message
    |
    v
Correction Detector
    |
    +-> normal question
    |
    +-> candidate correction
             |
             v
       structure candidate
             |
             v
       learning_save()
```

Do not persist every message.

## 11. Learning Recall Harness

Before investigation:

```text
User Question
    |
    v
learning_recall(question)
    |
    v
relevant learned rules
    |
    v
Investigation Plan
```

Example:

```text
Question:
"叫料轮询时间在哪？"

Recalled rule:
"配置查询必须遍历配置目录，不能只 grep"
```

## 12. Learning Precedence

```text
Manual confirmed project override
    >
User confirmed Learning Memory
    >
Validated Project Knowledge
    >
Strong inference
    >
Weak inference
```

Current runtime evidence wins for current state if it conflicts with learned historical rules.

## 13. Learning Tests

Required:

1. Explicit "记住" creates a persistent learning record.
2. Restart process and verify the rule still exists.
3. Related future question recalls the rule.
4. Persistence failure must prevent "已记住" wording.
5. Unrelated conversation must not be saved as a learning rule.

# PART B — DEEP PROJECT BOOTSTRAP

## 14. Problem

Current Bootstrap must move beyond:

```text
project tree
tech stack
limited tables
limited models
limited enums
```

It must build durable understanding of:

```text
module responsibilities
configuration system
critical business flows
Controller -> Service -> Mapper -> Table chains
business terminology
external system relationships
runtime-vs-static configuration priority
```

## 15. New Bootstrap Strategy

```text
Stage 1  Project Map
Stage 2  Module Discovery
Stage 3  Config Discovery
Stage 4  DB Semantics
Stage 5  Code Relationship Review
Stage 6  Core Business Flow Learning
Stage 7  External System Mapping
Stage 8  GLM Synthesis
Stage 9  Validation
Stage 10 Persist Knowledge
```

## 16. Stage 1 — Project Map

Read:

```text
directory tree
README
startup scripts
pom.xml
package.json
requirements
major config entry files
deployment scripts
```

Output:

```text
modules
runtime components
languages/frameworks
likely entry points
important directories
```

Persist as `project_overview`.

## 17. Stage 2 — Module Discovery

For each major module, collect:

```text
module role
entry files
key services
key APIs
related tables
related configs
external dependencies
```

Do not hardcode TASK-013 module names in generic logic.

## 18. Stage 3 — Config Discovery

Add a dedicated:

```text
ConfigCatalog
```

It must enumerate allowed config directories and files.

Support at minimum:

```text
.json
.yml
.yaml
.properties
.env
.ini
.conf
.xml
```

Do not rely only on grep.

## 19. Config Catalog Schema

Persist:

```text
config_id
file_path
relative_path
key
value_type
default_value
business_meaning
unit
read_by
priority
runtime_scope
confidence
last_verified
```

Do not persist secrets.

Use SecretRedactor before persistence or model use.

## 20. Config Resolution Rules

Where evidence exists, detect precedence such as:

```text
environment variable
    >
external ProgramData config
    >
project config
    >
hardcoded default
```

Persist as `config_priority_rules`.

Do not infer priority without evidence.

## 21. Config Query Harness

Add:

```text
config_lookup(query)
```

Runtime path:

```text
User Question
    |
    v
Intent Router -> configuration
    |
    v
learning_recall()
    |
    v
config_lookup()
    |
    v
optional code verification
    |
    v
Answer
```

Configuration questions should prefer ConfigCatalog before code grep/search.

## 22. Stage 4 — Database Semantics

Use:

```text
runtime schema
models/entities
repositories
mappers
SQL usage
service usage
```

to classify tables and persist:

```text
business role
current_state/history/callback/etc.
important fields
time fields
status fields
readers/writers
```

Do not mark business meaning as confirmed from table names alone.

## 23. Stage 5 — Code Relationship Review

Use existing code graph/scanners and include:

```text
Controller
Service
Mapper / Repository
Entity
SQL
Table
Config readers
Enum/state usage
```

The GLM synthesis stage must receive these relationships as structured evidence.

## 24. Stage 6 — Core Business Flow Learning

Discover candidate flows from:

```text
APIs
service names
frontend labels
state transitions
database tables
user-facing terminology
```

For each important flow, deep-read the exact relevant chain.

Recommended structure:

```text
Business Flow
├─ name
├─ aliases
├─ entry API
├─ controller
├─ services
├─ mapper/repository
├─ tables
├─ states
├─ configs
├─ external systems
├─ source of truth
├─ evidence
└─ confidence
```

## 25. Stage 7 — External System Mapping

Identify:

```text
PLC
robot
MES
WMS
third-party API
local service
database
file exchange
```

Persist:

```text
system name
connection type
used by module
config source
related logs
related APIs
```

Never persist credentials.

## 26. Stage 8 — Multi-pass GLM Synthesis

Do not use one giant prompt.

Recommended passes:

```text
Pass 1: Project/module summary
Pass 2: Config semantics
Pass 3: Database/table semantics
Pass 4: Business flows
Pass 5: Source of Truth
Pass 6: External integrations
Pass 7: Terminology/aliases
```

Each pass must return structured JSON.

## 27. Stage 9 — Validation

Validate:

```text
file exists
symbol exists
table exists
field exists
config file exists
config key exists
relationship evidence exists
API exists
service exists
mapper exists
```

Unsupported facts must be downgraded:

```text
confirmed
-> strongly_inferred
-> inferred
-> unknown
```

Never upgrade uncertain facts automatically.

## 28. Stage 10 — Persist Knowledge

Expand project knowledge storage to include:

```text
project_overview
modules
business_concepts
business_flows
database_tables
source_of_truth
config_catalog
config_priority_rules
apis
services
code_relationships
states
external_systems
operational_rules
```

SQLite + JSON is sufficient.

No vector database is required.

## 29. Bootstrap Read Strategy

Do not let GLM read the entire repository blindly.

Use:

```text
deterministic scan
    ->
identify important files
    ->
deep-read selected files
    ->
structured synthesis
```

Deep-read:

```text
core controllers
core services
mappers
critical config loaders
state enums
startup logic
```

## 30. Deep Read Limits

Add configurable limits:

```text
max_modules
max_files_per_module
max_lines_per_file
max_glm_rounds
```

Print progress, for example:

```text
[Bootstrap]
Project Map: done
Config Catalog: 42 files / 186 keys
DB Semantics: 17 core tables
Code Deep Read: 28 files
Business Flows: 6
Validation: passed
```

## 31. Query Intent Router

Recommended intents:

```text
configuration
business_data
code_structure
runtime_fault
version
history
general
```

Examples:

```text
"配置在哪"
-> configuration

"最新一托"
-> business_data

"这个接口最后写哪张表"
-> code_structure

"为什么今天卡住"
-> runtime_fault
```

## 32. Runtime Harness by Intent

Configuration:

```text
learning_recall
-> config_lookup
-> optional code verification
```

Business Data:

```text
learning_recall
-> project_lookup
-> source of truth
-> DB/log reader
```

Code Structure:

```text
project_lookup
-> code graph
-> exact code_read
```

Runtime Fault:

```text
learning_recall
+ project_lookup
+ incident memory
-> version/log/db/code investigation
```

## 33. Queryable Project Knowledge

Add/extend:

```text
project_lookup(query)
config_lookup(query)
flow_lookup(query)
module_lookup(query)
```

Return compact structured results.

## 34. Learning + Project Knowledge Interaction

When a correction affects Project Knowledge:

```text
User Correction
    |
    v
Learning Memory
    |
    v
candidate project override
```

Do not automatically rewrite the Blueprint.

Automatic promotion to project override is optional.

# VALIDATION

## 35. TASK-013 Case 1 — Configuration Memory

Conversation:

```text
User:
查询叫料轮询配置

Agent initially misses correct file.

User:
记住：查询配置应该遍历配置目录中的所有配置文件，不能只用 grep。
```

Expected:

```text
learning_save succeeds
```

Restart IRO_agent.

Ask again:

```text
查询叫料轮询配置
```

Expected:

```text
learning_recall
-> config_lookup
-> ordersys-settings.json
```

The rule must survive restart.

## 36. TASK-013 Case 2 — Project Bootstrap Depth

Run:

```text
iro-agent init --refresh
```

Expected knowledge must contain:

```text
project overview
module knowledge
config catalog
database semantics
business flows
code relationships
source of truth
external systems
```

Not only table/model/enum lists.

## 37. TASK-013 Case 3 — Config Catalog

Bootstrap must discover `ordersys-settings.json` and relevant keys.

If `materialCallPollIntervalSeconds` exists, it must be searchable in Project Knowledge.

## 38. TASK-013 Case 4 — Business Flow

Choose one known flow and verify:

```text
business concept
-> API
-> service
-> mapper/repository
-> table
-> status/config if relevant
```

Every step must retain evidence.

## 39. TASK-013 Case 5 — Restart-safe Learning

1. Store a correction rule.
2. Stop CLI/gateway.
3. Restart.
4. Ask a related question.

Expected:

```text
relevant learned rule is recalled
```

# TESTING

## 40. Required Tests

Add:

```text
test_learning_memory.py
test_learning_recall.py
test_correction_detection.py
test_config_catalog.py
test_deep_bootstrap.py
test_bootstrap_business_flows.py
test_intent_router.py
```

Add at least one restart-persistence test.

## 41. Regression Requirements

Existing features must remain intact:

```text
read-only DB
read-only code access
VersionReader
Incident Memory
Feishu Gateway
Project Lookup
Secret Redaction
```

No regression in current TASK-013 ground-truth tests.

# SECURITY

## 42. Security Rules

Learning Memory and Project Knowledge are the only writable areas added.

Allowed writes:

```text
IRO_agent SQLite
.iro_agent knowledge files
internal logs
```

Forbidden:

```text
project source modification
runtime config modification
database writes
Git writes
service restart
deployment
PLC/robot control
```

Config scanner must redact secrets before persistence or GLM context.

# IMPLEMENTATION

## 43. Suggested File Structure

```text
iro_agent/
├─ memory/
│  ├─ incident_store.py
│  └─ learning_store.py
│
├─ knowledge/
│  ├─ bootstrap.py
│  ├─ config_catalog.py
│  ├─ business_flows.py
│  ├─ store.py
│  ├─ validator.py
│  └─ lookup.py
│
├─ router/
│  └─ intent_router.py
```

Adapt to current architecture where cleaner.

## 44. Development Phases

### Phase 1 — Durable Learning Store
Implement LearningMemoryStore, learning_save, learning_recall.

### Phase 2 — Correction Detection
Detect explicit correction and remember intent.

### Phase 3 — Memory Harness
Recall learned rules before investigation.

### Phase 4 — Config Catalog
Enumerate config directories/files/keys.

### Phase 5 — Project Map Upgrade
Improve project/module overview.

### Phase 6 — Deep Code Read
Select and read critical files using existing code graph.

### Phase 7 — Business Flow Knowledge
Build structured flows.

### Phase 8 — Multi-pass GLM Synthesis
Replace shallow one-pass summary.

### Phase 9 — Validator Upgrade
Validate project/config/code facts.

### Phase 10 — Intent Router
Route configuration/business/code/fault questions.

### Phase 11 — Runtime Harness Integration
Ensure learned rules and project knowledge affect tool selection.

### Phase 12 — TASK-013 Regression + Real Tests
Validate with real operator questions.

## 45. Recommended Commit Sequence

```text
01 feat: add durable learning memory store
02 feat: add learning save and recall tools
03 feat: add correction and remember intent detection
04 refactor: recall learned rules before investigation
05 feat: add config catalog scanner
06 feat: add config lookup tool
07 refactor: deepen project map bootstrap
08 feat: add module-level deep code reading
09 feat: add business flow knowledge model
10 feat: add multi-pass glm bootstrap synthesis
11 feat: upgrade project knowledge validation
12 feat: add query intent router
13 refactor: route config questions through config knowledge
14 refactor: route business questions through project knowledge
15 test: add durable learning restart persistence
16 test: add task013 config correction regression
17 test: add task013 deep bootstrap validation
18 docs: document learning memory and deep bootstrap
```

## 46. Definition of Done

V0.4 is complete when:

- user corrections survive process restart
- `learning_recall()` returns relevant rules
- the agent only says "remembered" after persistence succeeds
- configuration queries no longer depend on grep-only behavior
- ConfigCatalog enumerates allowed config directories/files
- important config keys are searchable
- `iro-agent init` produces deep project knowledge
- bootstrap contains module responsibilities
- bootstrap contains config knowledge
- bootstrap contains business flows
- bootstrap contains code relationship evidence
- bootstrap contains DB semantics
- bootstrap contains Source of Truth rules
- GLM synthesis is multi-pass, not one shallow summary
- runtime queries use intent routing
- configuration questions prefer ConfigCatalog
- business questions prefer Project Knowledge
- code questions prefer Code Graph + exact code evidence
- runtime fault questions combine Learning + Project + Incident knowledge
- TASK-013 real regression cases pass
- no production write capability is introduced

## 47. Final Target Behavior

```text
User:
"叫料轮询在哪里配置？"

IRO_agent:
1. recognizes configuration intent
2. recalls prior learned rules
3. searches ConfigCatalog
4. identifies the relevant config file/key
5. optionally verifies which code reads it
6. answers with evidence
```

After:

```text
"记住：以后查配置要遍历所有配置文件，不能只 grep。"
```

IRO_agent must:

```text
persist the rule
    ->
survive restart
    ->
recall it later
    ->
change future investigation behavior
```

The intended end state is:

> IRO_agent behaves like a long-term resident engineer who both understands the project and learns from operator corrections over time.
