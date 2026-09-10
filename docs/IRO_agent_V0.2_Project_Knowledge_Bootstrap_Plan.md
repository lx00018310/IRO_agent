# IRO_agent V0.2 — Project Knowledge Bootstrap Plan

## 1. Goal

Add a persistent **Project Knowledge / Project Blueprint** layer to IRO_agent.

The purpose is to improve diagnostic and database-query accuracy by giving the agent a stable understanding of:

- what the project contains
- what each module does
- what the important database tables mean
- which data source is authoritative for each business fact
- which fields/states represent which business concepts
- how important modules, APIs, services, and tables relate

This must not be implemented as temporary conversation memory.

The new architecture should separate:

```text
Project Knowledge
Runtime Evidence
Incident Memory
Conversation Memory
```

The primary new workflow is:

```text
iro-agent init
        |
        v
scan project structure
        |
        v
scan code / models / schema / config
        |
        v
build Project Blueprint
        |
        v
persist locally
        |
        v
daily question
        |
        v
project_lookup()
        |
        v
Reader selection + factual query
        |
        v
diagnostic answer
```

The first validation target remains:

**TASK-013**

---

# 2. Core Design Principle

IRO_agent must not rely on the LLM to guess project semantics from table names or file names during every question.

Instead:

> **Project semantics are learned during initialization, persisted, and retrieved before factual investigation.**

Examples:

```text
"最新一托"
    ->
canonical business concept
    ->
ordersys_dock_task.current_pallet_slot
```

```text
"调度回执"
    ->
historical integration receipt
    ->
ordersys_dispatch_callback_receipt
```

The agent must understand that these two concepts are not interchangeable.

---

# 3. Memory Separation

Introduce four clearly separated knowledge layers.

## 3.1 Project Knowledge

Answers:

> What is this system?

Persistent and relatively stable.

Contains:

- modules
- business concepts
- tables
- fields
- APIs
- state values
- source-of-truth rules
- component relationships
- important code locations

## 3.2 Runtime Evidence

Answers:

> What is happening now?

Read live from:

- database
- logs
- active version provider
- runtime files/configuration where permitted

Never persist runtime state as Project Knowledge unless explicitly promoted.

## 3.3 Incident Memory

Answers:

> What problems happened before?

Contains:

- incidents
- timelines
- fault domains
- impact
- root causes
- historical resolutions
- related runtime evidence

## 3.4 Conversation Memory

Answers:

> What were we just discussing?

Short-term session context only.

Project facts must not depend on conversation history.

---

# 4. New CLI Function

Add:

```text
iro-agent init
```

Optionally expose it in the interactive menu as:

```text
[6] 初始化 / 更新项目认知 (Project Bootstrap)
```

Adjust menu numbering as needed.

The command must support:

```text
iro-agent init
iro-agent init --project TASK-013
iro-agent init --refresh
```

Minimum behavior:

1. load project configuration
2. validate configured source paths
3. inspect project structure
4. inspect database schema if configured
5. inspect selected code areas
6. ask GLM to synthesize structured project knowledge
7. validate generated knowledge
8. save Project Blueprint
9. print summary
10. do not modify the target project

---

# 5. Project Blueprint Storage

Recommended path:

```text
.iro_agent/
    project_blueprint.json
```

Optional human-readable export:

```text
.iro_agent/
    project_blueprint.md
```

JSON is the canonical machine-readable format.

Markdown is optional for debugging/review.

Do not store the entire source code.

Do not store raw database rows unless required as evidence during bootstrap.

---

# 6. Project Blueprint Data Model

Recommended top-level structure:

```json
{
  "project": {},
  "modules": [],
  "business_concepts": [],
  "data_sources": [],
  "database_tables": [],
  "states": [],
  "apis": [],
  "relationships": [],
  "source_of_truth_rules": [],
  "code_locations": [],
  "metadata": {}
}
```

---

# 7. Project Metadata

Minimum fields:

```text
project_id
project_name
generated_at
last_verified_at
blueprint_version
source_root
active_version_provider
database_type
```

---

# 8. Module Knowledge

Each discovered module should store:

```text
module_id
name
business_role
technical_type
main_paths
related_tables
related_apis
confidence
sources
```

---

# 9. Business Concept Knowledge

This is the most important part.

Each concept should map natural business language to system representations.

Recommended fields:

```text
concept_id
name
aliases
description
canonical_source
secondary_sources
do_not_use_as_primary
related_fields
related_modules
query_guidance
confidence
sources
last_verified
```

Example:

```json
{
  "concept_id": "current_pallet",
  "name": "当前托盘",
  "aliases": [
    "最新一托",
    "当前一托",
    "现在这托",
    "正在处理的托盘"
  ],
  "description": "Current pallet associated with the latest dock task",
  "canonical_source": {
    "type": "database",
    "table": "ordersys_dock_task",
    "field": "current_pallet_slot"
  },
  "secondary_sources": [
    "related application logs"
  ],
  "do_not_use_as_primary": [
    "ordersys_dispatch_callback_receipt"
  ],
  "confidence": "confirmed"
}
```

---

# 10. Source of Truth Rules

Create explicit **Source of Truth** rules.

This is mandatory.

Each rule defines which system source is authoritative for a specific business fact.

Recommended fields:

```text
fact
canonical_source
secondary_sources
invalid_primary_sources
reason
confidence
sources
```

Example:

```json
{
  "fact": "当前月台正在处理哪一托",
  "canonical_source": "ordersys_dock_task.current_pallet_slot",
  "secondary_sources": [
    "dispatch logs"
  ],
  "invalid_primary_sources": [
    "ordersys_dispatch_callback_receipt"
  ],
  "reason": "callback_receipt is historical integration receipt data",
  "confidence": "confirmed"
}
```

Another example:

```json
{
  "fact": "第三方是否回调某次调度完成",
  "canonical_source": "ordersys_dispatch_callback_receipt",
  "secondary_sources": [
    "integration logs"
  ],
  "confidence": "confirmed"
}
```

The agent must prefer Source of Truth rules over table-name guessing.

---

# 11. Database Table Knowledge

For important tables, store:

```text
table_name
business_role
table_type
important_fields
time_fields
primary_key
status_fields
relationships
recommended_queries
not_for
confidence
sources
```

Recommended `table_type` values:

```text
current_state
master
transaction
history
callback
audit
configuration
mapping
unknown
```

---

# 12. State / Enum Knowledge

Scan and persist important state values.

Recommended fields:

```text
name
value
business_meaning
source_location
related_table
related_field
confidence
```

---

# 13. API Knowledge

For important APIs:

```text
method
path
business_role
controller
service
related_tables
request_fields
response_fields
confidence
sources
```

Do not attempt to document every trivial endpoint.

Prioritize business-critical APIs.

---

# 14. Code Location Knowledge

Store important code entry points.

Example:

```text
business concept
module
file
symbol
purpose
```

This helps the model know where to inspect deeper when required.

---

# 15. Confidence and Provenance

Every important Blueprint fact should contain:

```text
confidence
sources
last_verified
```

Allowed confidence:

```text
confirmed
strongly_inferred
inferred
unknown
```

Source examples:

```text
runtime_database_schema
entity_model
repository_sql
service_code
controller_code
configuration
manual_override
```

A fact derived only from naming conventions should not be `confirmed`.

---

# 16. Bootstrap Scanner

Do not let GLM freely roam through the entire repository.

Create a deterministic bootstrap pipeline.

Recommended stages:

```text
Stage 1 — Project Tree
Stage 2 — Technology Detection
Stage 3 — Database Schema
Stage 4 — Models / Entities
Stage 5 — Repository / Mapper / SQL
Stage 6 — Core Services
Stage 7 — Controllers / APIs
Stage 8 — State Enums
Stage 9 — Config
Stage 10 — Knowledge Synthesis
Stage 11 — Validation
Stage 12 — Persist Blueprint
```

---

# 17. Stage 1 — Project Tree

Scan directory structure with exclusions.

Exclude at minimum:

```text
.git
node_modules
dist
build
target
cache
logs
runtime
temporary files
binary packages
```

Use existing security allowlists.

Do not scan outside configured project root.

---

# 18. Stage 2 — Technology Detection

Detect:

```text
Java / Spring Boot
Vue
Python
Node
database type
ORM technology
SQL mapper technology
configuration formats
```

This determines later scan strategy.

Do not hardcode TASK-013-only assumptions into the generic bootstrap framework.

---

# 19. Stage 3 — Runtime Database Schema

If a database is configured, inspect metadata using read-only queries.

Add metadata capabilities such as:

```text
db_list_tables
db_describe_table
db_foreign_keys
```

These tools must use database metadata APIs / information_schema.

Do not rely on GLM-generated arbitrary SQL for metadata discovery.

Collect:

```text
table names
column names
types
primary keys
foreign keys
comments if available
```

---

# 20. Stage 4 — Models / Entities

Target files matching the detected stack.

Examples:

```text
*Entity.java
*Model.java
*PO.java
*DO.java
models/
entities/
domain/
```

Extract:

```text
table mapping
field mapping
comments
enum references
relationships
```

Use deterministic parsing/search first.

Use GLM for semantic interpretation second.

---

# 21. Stage 5 — Repository / Mapper / SQL

Inspect:

```text
Repository
DAO
Mapper
XML SQL
SQL files
query builders
```

Purpose:

Determine:

- which tables are actively used
- which queries represent current state
- which queries represent history
- ordering/time rules
- table joins
- business access patterns

This stage is critical for Source of Truth inference.

---

# 22. Stage 6 — Core Services

Inspect selected business Services.

Do not read every service by default.

Prioritize services referenced by:

- important tables
- key APIs
- state transitions
- core business modules

Extract:

```text
business actions
table usage
state transitions
external interactions
```

---

# 23. Stage 7 — Controllers / APIs

Map user-visible business operations to backend implementation.

Extract:

```text
API
Controller
Service
Table
```

This creates useful business-to-technical paths.

---

# 24. Stage 8 — State Enums

Scan:

```text
enum
constants
status mappings
state-machine definitions
```

Persist business meanings where evidence exists.

Do not invent undocumented meanings.

---

# 25. Stage 9 — Configuration

Read selected non-secret configuration.

Use SecretRedactor before any content reaches GLM.

Extract only:

```text
module relationships
database names
service names
ports
feature flags
paths
external system names
```

Never persist:

```text
passwords
tokens
API keys
private keys
credentials
```

---

# 26. Stage 10 — Knowledge Synthesis

GLM-5.3-Flash should synthesize structured knowledge from the collected evidence.

The model must produce structured JSON matching the Blueprint schema.

Do not ask:

```text
"Please summarize this project."
```

Instead issue focused synthesis tasks:

```text
Identify business roles of these tables.
Identify likely current-state vs history tables.
Map business concepts to canonical sources.
Identify state meanings.
Map APIs to services/tables.
```

---

# 27. Stage 11 — Blueprint Validation

Before saving, validate generated knowledge.

Validation rules:

1. Referenced table must exist in runtime schema or code evidence.
2. Referenced field must exist.
3. Referenced file must exist.
4. Confirmed facts require at least one strong source.
5. Source of Truth rules should preferably have multiple supporting signals.
6. Invalid references must be downgraded or removed.
7. Secrets must not appear.
8. Unknown facts remain unknown.

---

# 28. Runtime Schema vs Code Conflict

When runtime database schema and code disagree, record the conflict.

Default priority for runtime facts:

```text
Runtime DB Schema
    >
Static Code Assumption
```

But do not automatically assume business meaning solely from runtime schema.

---

# 29. Project Knowledge Store

Create a dedicated component:

```text
ProjectKnowledgeStore
```

Responsibilities:

```text
load blueprint
save blueprint
search knowledge
get concept
get table
get source-of-truth rule
get module
get state
```

Do not store Project Blueprint through IncidentStore.

---

# 30. Project Lookup Tool

Add a new read-only agent tool:

```text
project_lookup(query)
```

Purpose:

Retrieve relevant project knowledge before using lower-level tools.

Example:

```text
project_lookup("最新一托 调度")
```

Possible response:

```json
{
  "concepts": [
    {
      "name": "当前托盘",
      "canonical_source": "ordersys_dock_task.current_pallet_slot"
    }
  ],
  "tables": [
    {
      "name": "ordersys_dock_task",
      "role": "月台主任务状态"
    }
  ],
  "warnings": [
    "ordersys_dispatch_callback_receipt is historical callback data and should not be used as the current pallet source"
  ]
}
```

---

# 31. Do Not Inject Entire Blueprint Into Every Prompt

Do not permanently inject the entire Blueprint.

Instead:

```text
User question
    |
    v
Project Knowledge retrieval
    |
    v
Relevant 5–15 facts
    |
    v
LLM context
```

This keeps context small and supports larger projects.

A minimal project summary may be injected globally, but detailed table/state knowledge should be retrieved dynamically.

---

# 32. Query Harness Update

The runtime harness should become:

```text
User Question
      |
      v
Intent / Business Concept Detection
      |
      v
project_lookup()
      |
      v
Does Blueprint identify authoritative source?
      |
   +--+--+
   |     |
  yes    no
   |     |
   v     v
direct  metadata/code
Reader  investigation
   |     |
   +--+--+
      |
      v
Runtime Evidence
      |
      v
Answer
```

For database questions, preferred order:

```text
project_lookup
    ->
db_describe_table if needed
    ->
db_query
```

Do not let the model start with arbitrary table guessing when Blueprint knowledge exists.

---

# 33. Database Metadata Tools

Add generic read-only tools:

```text
db_list_tables
db_describe_table
```

Optional:

```text
db_find_columns
db_foreign_keys
```

These are metadata tools.

They should not replace `db_query`.

They exist for cases where Project Knowledge is missing or uncertain.

---

# 34. DB Query Guardrail

`db_query` remains available as a generic read-only fallback.

Update its tool description to state:

```text
Before querying business data:
1. prefer Project Knowledge
2. identify canonical source
3. verify schema if uncertain
4. then issue SELECT
```

Do not hardcode TASK-013 SQL into the generic DatabaseReader.

---

# 35. Project Knowledge Freshness

Store:

```text
generated_at
last_verified_at
source_fingerprint
```

A simple source fingerprint may include:

```text
active version id
schema signature
important file modification hashes
```

At startup, detect likely staleness.

Example:

```text
Project Blueprint may be stale.
Current source version differs from last initialization.
Run:
iro-agent init --refresh
```

Do not automatically rebuild during normal chat.

---

# 36. Refresh Behavior

`iro-agent init --refresh` should:

1. preserve the old Blueprint as backup
2. scan current project
3. generate new Blueprint
4. compare old/new
5. show meaningful changes
6. replace active Blueprint only after validation

Recommended backup:

```text
project_blueprint.history/
```

Keep a small number of historical Blueprint versions.

---

# 37. Manual Override

Allow a human to correct important knowledge without modifying project code.

Optional file:

```text
.iro_agent/project_knowledge_override.json
```

Use for facts such as:

```text
"当前一托必须以 ordersys_dock_task 为准"
```

Priority:

```text
Manual confirmed override
    >
Validated Blueprint inference
```

Do not implement a GUI editor.

JSON/YAML editing is sufficient for V0.2.

---

# 38. TASK-013 Bootstrap Validation

Use TASK-013 as the first validation project.

The generated Blueprint must correctly distinguish at minimum:

```text
ordersys_dock_task
ordersys_dispatch_callback_receipt
```

Expected understanding:

### ordersys_dock_task

Must be identified as the primary current dock/task state source if supported by code/schema evidence.

### ordersys_dispatch_callback_receipt

Must be identified as historical/integration callback receipt data if supported by evidence.

The exact wording may vary.

The distinction must be correct.

---

# 39. Primary Real Validation Question

After initialization, test:

```text
查询数据库最新一托的调度信息
```

Expected tool flow should approximately be:

```text
project_lookup
    ->
identify canonical source
    ->
optional db_describe_table
    ->
db_query against correct current-state table
```

The agent should not query unrelated historical callback tables unless needed for an explicitly requested comparison.

---

# 40. Additional TASK-013 Validation Questions

Use at least these:

## Test A

```text
查询最新一托的调度信息
```

Expected:

Use current-state canonical source.

## Test B

```text
查询这托有没有收到调度完成回执
```

Expected:

Use callback/receipt source.

## Test C

```text
当前11号月台正在处理什么？
```

Expected:

Use current dock/task state source.

## Test D

```text
这个状态 COMPLETED 是什么意思？
```

Expected:

Use Project Knowledge state definition plus runtime evidence if needed.

## Test E

```text
这个接口的数据最后写到哪张表？
```

Expected:

Use API/service/repository/code-location knowledge.

---

# 41. Accuracy Evaluation

Create a small ground-truth evaluation file.

Example:

```text
tests/project_knowledge_ground_truth.json
```

Each case contains:

```text
question
expected_concept
expected_primary_source
forbidden_primary_sources
```

Example:

```json
{
  "question": "查询最新一托的调度信息",
  "expected_primary_source": "ordersys_dock_task",
  "forbidden_primary_sources": [
    "ordersys_dispatch_callback_receipt"
  ]
}
```

A test should fail if the wrong primary source is selected even if the final natural-language answer looks plausible.

---

# 42. Observability

During CLI testing, show Project Knowledge retrieval.

Example:

```text
[项目认知] -> project_lookup
  concept: 当前托盘
  canonical source: ordersys_dock_task.current_pallet_slot
  confidence: confirmed
```

This is useful for debugging accuracy.

Do not show excessive internal chain-of-thought.

Only show retrieved structured knowledge and tool calls.

---

# 43. Security Requirements

Project Bootstrap must remain read-only.

It may:

```text
read project files
read database metadata
read source code
write .iro_agent Blueprint files
```

It must not:

```text
modify project source
modify database
execute project scripts
run arbitrary shell commands
deploy
restart services
modify Git
```

All SecretRedactor rules remain mandatory.

---

# 44. Explicit Non-Goals

Do not implement during this plan:

```text
vector database
Milvus
Elasticsearch
generic RAG platform
full code embedding
CodeGraph expansion
automatic bug repair
automatic SQL optimization
GUI
EXE
new Gateway features
Feishu cards
dashboard
automatic project modification
```

SQLite / JSON / FTS is sufficient for initial Project Knowledge retrieval.

---

# 45. Recommended File Structure

Suggested:

```text
iro_agent/
├─ knowledge/
│  ├─ __init__.py
│  ├─ models.py
│  ├─ store.py
│  ├─ bootstrap.py
│  ├─ scanner.py
│  ├─ schema_scanner.py
│  ├─ code_scanner.py
│  ├─ synthesizer.py
│  ├─ validator.py
│  └─ lookup.py
```

Do not force this exact structure if current architecture has a cleaner fit.

Keep responsibilities separated.

---

# 46. Recommended Development Phases

## Phase 1
Define Blueprint schema and ProjectKnowledgeStore.

## Phase 2
Implement project tree + technology scan.

## Phase 3
Implement database metadata scanner.

## Phase 4
Implement code/model/repository/service/API targeted scanner.

## Phase 5
Implement GLM structured knowledge synthesis.

## Phase 6
Implement Blueprint validator.

## Phase 7
Implement `iro-agent init`.

## Phase 8
Implement `project_lookup`.

## Phase 9
Integrate Project Knowledge into Agent harness.

## Phase 10
Add DB metadata tools.

## Phase 11
Add Blueprint freshness/refresh.

## Phase 12
Run TASK-013 ground-truth tests.

Do not start the next phase before the previous phase has tests.

---

# 47. Recommended Commit Sequence

```text
01 feat: add project blueprint schema
02 feat: add project knowledge store
03 feat: add project structure scanner
04 feat: add database metadata scanner
05 feat: add targeted code knowledge scanner
06 feat: add glm project knowledge synthesizer
07 feat: add blueprint validation
08 feat: add iro-agent init command
09 feat: add project lookup tool
10 refactor: consult project knowledge before database queries
11 feat: add database metadata tools
12 feat: add blueprint freshness and refresh flow
13 test: add task013 project knowledge ground truth
14 test: add latest pallet canonical-source validation
15 docs: document project bootstrap workflow
```

---

# 48. Definition of Done

V0.2 Project Knowledge is complete when:

- `iro-agent init` runs successfully on TASK-013.
- A persistent Project Blueprint is generated.
- Project Knowledge is stored separately from Incident Memory.
- Project Knowledge is stored separately from Conversation Memory.
- Important TASK-013 modules are identified.
- Important database tables have business roles.
- Source of Truth rules are generated.
- Business concepts can map to canonical sources.
- Table/field references are validated against real schema/code evidence.
- Important states are represented.
- Important code locations are represented.
- `project_lookup()` retrieves relevant knowledge.
- Normal queries do not inject the entire Blueprint.
- Database questions consult Project Knowledge before arbitrary SQL.
- Metadata tools can resolve uncertainty.
- Unknown knowledge remains unknown.
- Secrets do not enter the Blueprint.
- Refresh detects meaningful project changes.
- TASK-013 ground-truth tests pass.
- The question `查询数据库最新一托的调度信息` selects the correct authoritative data source.
- The callback receipt table is not incorrectly used as the primary current-pallet source.

---

# 49. Final Design Principle

IRO_agent should no longer behave like:

```text
User Question
    ->
LLM guesses table/file
    ->
Reader
```

It should behave like:

```text
User Question
    |
    v
Project Knowledge
    |
    v
Business Concept
    |
    v
Source of Truth
    |
    v
Runtime Reader
    |
    v
Evidence
    |
    v
Answer
```

The purpose of Project Bootstrap is not to make the model "remember more".

The purpose is to make IRO_agent understand:

> **What each part of this industrial system actually means, and where the authoritative facts live.**
