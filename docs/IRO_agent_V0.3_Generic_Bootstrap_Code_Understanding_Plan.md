# IRO_agent V0.3 — Generic Industrial Project Bootstrap & Code Understanding Plan

## 1. Goal

Upgrade IRO_agent from a TASK-013-oriented project learner into a **generic industrial project learning engine**.

The two major goals are:

1. Remove TASK-013-specific business knowledge from generic Bootstrap code.
2. Improve code understanding so IRO_agent can reconstruct real industrial software relationships such as:

```text
Business Concept
    ->
API
    ->
Controller
    ->
Service
    ->
Repository / Mapper
    ->
SQL
    ->
Database Table
```

The first validation target remains TASK-013, but the implementation must be reusable for:

- MES
- WMS
- robot dispatch systems
- PLC integration software
- industrial HMI/backend systems
- Java/Spring projects
- MyBatis projects
- Vue frontend projects
- Python service projects
- mixed industrial software repositories

---

# 2. Core Design Principle

The generic Bootstrap engine must not contain hardcoded business facts such as:

```text
"最新一托" -> ordersys_dock_task
"调度回执" -> ordersys_dispatch_callback_receipt
```

Those facts belong to:

```text
Project Knowledge
Manual Override
Validated Project Blueprint
```

not to generic scanner/synthesizer code.

The generic engine should discover:

```text
what modules exist
what tables exist
where tables are used
which APIs call which services
which services call which repositories/mappers
which SQL reads/writes which tables
which states are used
which components communicate
```

Then GLM-5.3-Flash may infer business meaning from evidence.

---

# 3. Target Architecture

```text
                iro-agent init
                      |
                      v
              Project Bootstrap
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
 Project Tree    DB Schema      Code Scanner
                                  |
                  +---------------+----------------+
                  |               |                |
                  v               v                v
             Java/Spring       MyBatis          Vue/Python
                  |               |                |
                  +---------------+----------------+
                                  |
                                  v
                         Code Relationship Graph
                                  |
                                  v
                         Knowledge Synthesizer
                                  |
                                  v
                         Blueprint Validator
                                  |
                                  v
                         Project Blueprint
                                  |
                                  v
                           project_lookup()
```

---

# 4. Scope

This plan includes only:

- generic Bootstrap refactor
- removal of TASK-013 hardcoding
- language/framework scanner adapters
- Java/Spring structural analysis
- MyBatis analysis
- SQL-to-table mapping
- API-to-service-to-table mapping
- Vue API usage mapping
- Python project support cleanup
- code relationship graph
- improved Project Blueprint generation
- validation against TASK-013 and at least one synthetic second project

This plan does not include:

- new Gateway features
- GUI
- EXE
- automatic code modification
- vector database
- CodeGraph external dependency
- automatic remediation
- write access
- production deployment changes

---

# 5. Remove TASK-013 Hardcoding

Search the generic knowledge layer for project-specific logic.

Especially inspect:

```text
iro_agent/knowledge/synthesizer.py
iro_agent/knowledge/code_scanner.py
iro_agent/knowledge/lookup.py
iro_agent/knowledge/bootstrap.py
iro_agent/llm/glm_client.py
```

Remove logic that directly assumes:

```text
ordersys_dock_task
ordersys_dispatch_callback_receipt
dock_task
current_pallet_slot
"最新一托"
"调度回执"
TASK-013-specific module names
TASK-013-specific status semantics
```

Generic code may detect names, but must not assign fixed business meaning solely because a specific string appears.

Forbidden generic logic:

```python
if table_name == "ordersys_dock_task":
    role = "current dock state"
```

Correct direction:

```text
Scanner
  -> finds tables, fields, usages, SQL, services, APIs
Synthesizer
  -> infers candidate business meaning from evidence
Validator
  -> checks references and supporting evidence
Project-specific override
  -> may confirm or correct the result
```

---

# 6. Preserve Project-Specific Knowledge Separately

TASK-013-specific confirmed knowledge should be moved to:

```text
.iro_agent/project_knowledge_override.json
```

or another project-local configuration.

Example:

```json
{
  "source_of_truth_rules": [
    {
      "fact": "当前月台正在处理哪一托",
      "canonical_source": "ordersys_dock_task.current_pallet_slot",
      "confidence": "confirmed",
      "source": "manual_override"
    }
  ]
}
```

Generic Bootstrap must work when this file does not exist.

Priority:

```text
Manual Override
    >
Validated Blueprint
    >
Strong Inference
    >
Weak Inference
```

---

# 7. Introduce Scanner Adapter Architecture

Create a common scanner interface.

Recommended:

```text
CodeScannerAdapter
├─ detect()
├─ scan_models()
├─ scan_repositories()
├─ scan_services()
├─ scan_controllers()
├─ scan_states()
├─ scan_sql()
└─ scan_relationships()
```

Implement:

```text
JavaSpringScanner
MyBatisScanner
VueScanner
PythonScanner
GenericTextScanner
```

Each adapter should return normalized structures rather than free-form text.

---

# 8. Normalized Code Entity Model

Create a reusable code entity schema.

Recommended entity types:

```text
module
file
class
interface
method
function
controller
service
repository
mapper
entity
model
enum
api
sql_statement
database_table
database_field
config
external_endpoint
```

Recommended fields:

```text
entity_id
entity_type
name
qualified_name
file_path
start_line
end_line
framework
annotations
metadata
confidence
```

---

# 9. Relationship Model

Create a normalized relationship schema.

Recommended relationship types:

```text
CALLS
USES
IMPLEMENTS
EXTENDS
READS_TABLE
WRITES_TABLE
MAPS_TO_TABLE
EXPOSES_API
CALLS_SERVICE
CALLS_REPOSITORY
CALLS_MAPPER
USES_ENUM
USES_CONFIG
CALLS_EXTERNAL_API
REFERENCES_FIELD
RETURNS_MODEL
```

Recommended fields:

```text
source_entity_id
relationship_type
target_entity_id
evidence
confidence
```

The Project Blueprint should preserve these relationships.

---

# 10. Java / Spring Scanner

Implement structured Java/Spring analysis.

Detect annotations such as:

```text
@RestController
@Controller
@Service
@Component
@Repository
@Entity
@Table
@RequestMapping
@GetMapping
@PostMapping
@PutMapping
@DeleteMapping
@Autowired
@Resource
@RequiredArgsConstructor
```

Extract:

```text
class name
package
annotations
injected dependencies
method names
API paths
HTTP methods
service calls
repository calls
entity mappings
enum usage
```

Prefer a lightweight AST parser when practical, such as:

```text
tree-sitter-java
```

Do not introduce a heavy IDE/compiler dependency.

---

# 11. Java Entity / ORM Mapping

Support common ORM styles.

Detect:

```text
@Entity
@Table(name = "...")
@Column(name = "...")
@Id
```

Also support MyBatis-style POJO/entity classes where table names may be implied elsewhere.

Extract:

```text
entity class
table name
field -> column mapping
primary key
status fields
time fields
relationships
```

Cross-check against runtime database schema when available.

---

# 12. Spring API Mapping

Build:

```text
HTTP API
    ->
Controller Method
    ->
Service Method
```

Example normalized result:

```json
{
  "method": "POST",
  "path": "/orders/create",
  "controller": "OrderController.create",
  "service_calls": ["OrderService.createOrder"]
}
```

Compose class-level and method-level RequestMapping paths correctly.

---

# 13. Service Call Analysis

Within core services, extract direct method calls to:

```text
repositories
mappers
other services
external clients
state handlers
```

The goal is not full static analysis.

The goal is enough evidence to answer:

```text
这个接口最后经过哪些模块？
这个状态在哪里被修改？
这个业务最后写到了哪张表？
```

Support method-level evidence.

---

# 14. MyBatis Scanner

Implement explicit MyBatis support.

Detect:

```text
@Mapper
Mapper interfaces
XML mapper files
<select>
<insert>
<update>
<delete>
resultMap
parameterType
namespace
```

Map:

```text
Mapper Method
    ->
XML Statement
    ->
SQL
    ->
Database Tables
```

Example:

```text
DockTaskMapper.selectLatest
    ->
DockTaskMapper.xml#selectLatest
    ->
SELECT ... FROM ordersys_dock_task
```

This is high priority for industrial Java projects.

---

# 15. SQL Parser

Add a lightweight SQL analysis layer.

Required:

```text
identify SELECT tables
identify INSERT target
identify UPDATE target
identify DELETE target
identify JOIN tables
identify important WHERE fields
identify ORDER BY time/id fields
```

The scanner is analysis-only.

Do not execute discovered SQL during Bootstrap.

Use runtime DB metadata only for validation.

Recommended lightweight library if practical:

```text
sqlglot
```

---

# 16. Read vs Write Semantics

The Bootstrap engine may inspect write SQL even though IRO_agent itself is read-only.

This is necessary to understand:

```text
which service writes which table
which API changes which state
```

Clearly separate:

```text
Static analysis of write code = allowed
Executing write operations = forbidden
```

---

# 17. Table Usage Classification

For each database table, derive usage signals:

```text
read_count
write_count
used_by_services
used_by_apis
used_by_jobs
used_by_callbacks
ordered_by_time
frequently_updated
```

Then infer candidate table roles:

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

Do not assign these roles from table names alone.

Use evidence from:

```text
SQL usage
service usage
field structure
time fields
write patterns
API context
```

---

# 18. Source of Truth Inference

Improve Source of Truth generation.

For each business concept candidate, evaluate evidence such as:

```text
which table is directly updated by core workflow
which table is queried by current-status API
which table stores current state fields
which table is append-only history
which table is callback/audit only
which table contains latest state transitions
```

Generate:

```text
canonical_source candidate
secondary_sources
invalid_primary_sources
reason
confidence
```

Only use `confirmed` when evidence is strong or manually confirmed.

---

# 19. Business Concept Discovery

Do not hardcode business terms.

Discover candidate concepts from:

```text
controller names
API paths
service names
entity names
database comments
field comments
enum names
frontend labels
manual project description
```

GLM may group technical names into human concepts, but every concept must retain evidence.

---

# 20. Vue Scanner

Implement lightweight Vue/frontend analysis.

Detect:

```text
API client files
axios/fetch calls
route definitions
component names
user-facing labels
status mappings
```

Build relationships:

```text
Vue Component
    ->
Frontend API Function
    ->
Backend Endpoint
```

This improves answers such as:

```text
这个页面的数据来自哪个接口？
这个按钮最终调用哪个后端功能？
```

Do not attempt complete frontend AST analysis in V0.3.

---

# 21. Python Scanner

Preserve and improve Python support.

Detect:

```text
FastAPI
Flask
SQLAlchemy
Django models
service functions
repository/data-access functions
```

Normalize output to the same Code Entity and Relationship models.

---

# 22. Config and External System Scanner

Detect non-secret references to:

```text
PLC endpoints
robot endpoints
database names
HTTP endpoints
service names
ports
MQ topics
file paths
external system names
```

Use SecretRedactor before model interpretation.

Build relationships such as:

```text
Service A -> calls PLC endpoint
Service B -> calls Robot API
Backend -> uses Database X
```

Do not persist credentials.

---

# 23. Build a Local Code Relationship Graph

Do not add an external graph database.

Use lightweight storage, preferably SQLite.

Tables may include:

```text
code_entities
code_relationships
code_evidence
```

Support queries such as:

```text
find callers
find callees
find API path
find tables used by service
find services using table
find code path from API to table
```

This is not a vector database.

---

# 24. Project Knowledge Store Integration

ProjectKnowledgeStore should ingest:

```text
Blueprint semantic knowledge
+
Code Relationship Graph
```

But keep them logically separate:

```text
Semantic Knowledge = business meaning
Code Graph = structural relationships
```

`project_lookup()` may return both.

---

# 25. Enhance project_lookup()

Update output to include:

```text
business concepts
source-of-truth rules
database tables
related APIs
related services
related code paths
warnings
confidence
```

Example:

```text
project_lookup("最新一托调度")
```

may return:

```text
Concept:
当前托盘

Canonical Source:
ordersys_dock_task.current_pallet_slot

Related API:
GET /ordersys/...

Related Service:
DockTaskService

Related Mapper:
DockTaskMapper

Warnings:
dispatch_callback_receipt is historical callback data
```

---

# 26. Add Code Graph Query Tools

Add read-only tools:

```text
code_find_symbol
code_find_callers
code_find_callees
code_trace_api
code_find_table_usage
code_trace_api_to_table
```

Keep existing `code_search` and `code_read` if present.

Do not expose arbitrary filesystem access.

---

# 27. API-to-Table Trace

Implement:

```text
code_trace_api_to_table(api_path)
```

Expected output:

```text
POST /orders/create
    ->
OrderController.create
    ->
OrderService.createOrder
    ->
OrderMapper.insert
    ->
ordersys_order
```

Each step must include source-file and line evidence.

---

# 28. Table-to-Code Trace

Implement:

```text
code_find_table_usage(table_name)
```

Expected:

```text
ordersys_dock_task

Read by:
- DockTaskMapper.selectLatest
- DockTaskService.getCurrentTask

Written by:
- DockTaskMapper.updateStatus
- DispatchService.assignTask
```

Static write relationships are informational only.

No runtime write capability is added.

---

# 29. State Trace

Support questions such as:

```text
COMPLETED 状态在哪里设置？
```

Use:

```text
enum definition
field mapping
assignment sites
service method
database table
```

Return state meaning plus code evidence.

---

# 30. Bootstrap Execution Strategy

Avoid scanning the entire repository with the LLM.

Use:

```text
deterministic scan
    ->
structured extraction
    ->
small evidence batches
    ->
GLM semantic synthesis
```

The LLM should never receive the whole repository.

This reduces:

- token cost
- latency
- hallucination
- secret exposure

---

# 31. Incremental Bootstrap

Do not rebuild everything when only a few files change.

Store fingerprints:

```text
file hash
schema signature
active version id
```

On:

```text
iro-agent init --refresh
```

detect changed files and rescan only affected areas where practical.

V0.3 may use simple file hashes.

Do not over-engineer dependency invalidation.

---

# 32. Blueprint Validation Upgrade

Validator must verify:

```text
table exists
field exists
file exists
symbol exists
API mapping exists
service mapping exists
relationship evidence exists
```

If GLM proposes a relationship without code/SQL evidence, downgrade it to `inferred` or `unknown`.

Do not silently accept unsupported relationships.

---

# 33. Evidence Provenance

Every code relationship should keep evidence:

```text
file_path
line_start
line_end
evidence_type
raw_symbol/reference
```

Example:

```json
{
  "relationship": "CALLS_SERVICE",
  "source": "OrderController.create",
  "target": "OrderService.createOrder",
  "evidence": {
    "file": "OrderController.java",
    "line": 83
  }
}
```

This is required for trust and later review.

---

# 34. Generic Project Validation

Validation must include two projects.

## Project A — TASK-013

Must preserve current accuracy.

## Project B — Synthetic Industrial Fixture

Create a small synthetic project that does not use TASK-013 names.

Example domain:

```text
robot charging station
warehouse task
PLC handshake
```

The Bootstrap must infer structure without TASK-013-specific logic.

Tests should fail if generic code depends on TASK-013 names.

---

# 35. TASK-013 Regression Tests

Keep existing ground-truth questions.

At minimum:

```text
查询最新一托的调度信息
查询这托有没有收到完成回执
当前11号月台正在处理什么
这个状态 COMPLETED 是什么意思
这个接口的数据最后写到哪张表
```

The refactor must not reduce current accuracy.

---

# 36. New Code Understanding Tests

Add tests for:

- Java Controller -> Service
- Service -> Mapper
- Mapper -> SQL
- SQL -> Table
- Entity -> Table
- API -> Table end-to-end
- Table -> Code usage
- Enum -> Assignment Site

Every test should check structural output, not just final natural-language answers.

---

# 37. Accuracy Metrics

Add measurable metrics.

Recommended:

```text
Primary Source Accuracy
API-to-Table Trace Accuracy
Table-to-Code Trace Accuracy
State Trace Accuracy
Project Lookup Accuracy
False Relationship Rate
```

Example initial target for TASK-013:

```text
Primary Source Accuracy >= 90%
API-to-Table Trace Accuracy >= 85%
False Relationship Rate <= 10%
```

Do not optimize only for natural-language answer quality.

Measure structural correctness.

---

# 38. Runtime Harness Changes

At runtime:

```text
User Question
    |
    v
project_lookup
    |
    +-> business meaning
    +-> source of truth
    +-> related code path
    |
    v
Reader / DB / Log / Version
    |
    v
Evidence
    |
    v
LLM Answer
```

When a question is about code behavior:

```text
project_lookup
    ->
code graph query
    ->
code_read exact evidence
    ->
answer
```

---

# 39. Deterministic Routing for Known Structural Questions

For known structured requests, route directly where possible.

Examples:

```text
"这个接口写到哪张表"
    -> code_trace_api_to_table

"这张表谁在写"
    -> code_find_table_usage

"这个状态在哪里设置"
    -> state trace
```

GLM may interpret intent, but execution should use deterministic read-only tools.

---

# 40. Security

All new scanners are read-only.

Allowed:

```text
read source files
parse source files
read database metadata
write internal .iro_agent knowledge files
```

Forbidden:

```text
modify project files
compile project
execute project code
run migration
run SQL writes
modify Git
deploy
restart services
```

Static parsing of write code is allowed.

Execution of write operations is forbidden.

---

# 41. Dependencies

Prefer lightweight dependencies.

Candidates:

```text
tree-sitter
tree-sitter-java
sqlglot
```

Before adding a dependency, verify:

```text
maintenance status
license
Windows compatibility
Python compatibility
package size
```

Do not add large frameworks unless required.

---

# 42. Recommended File Structure

Suggested:

```text
iro_agent/
├─ knowledge/
│  ├─ scanners/
│  │  ├─ base.py
│  │  ├─ java_spring.py
│  │  ├─ mybatis.py
│  │  ├─ vue.py
│  │  ├─ python.py
│  │  └─ generic.py
│  ├─ code_entities.py
│  ├─ code_graph.py
│  ├─ relationships.py
│  ├─ synthesizer.py
│  ├─ validator.py
│  ├─ store.py
│  └─ lookup.py
```

Adapt to the current repository if a cleaner structure already exists.

---

# 43. Development Phases

## Phase 1 — Hardcoding Audit

- locate TASK-013-specific logic
- move project-specific facts to override/test fixtures
- add regression tests

## Phase 2 — Common Code Entity Model

- define code entities
- define relationships
- define evidence model

## Phase 3 — Java/Spring Scanner

- classes
- annotations
- APIs
- dependency injection
- service calls

## Phase 4 — ORM + MyBatis Scanner

- entities
- mapper interfaces
- XML SQL
- table mappings

## Phase 5 — SQL Analysis

- tables
- reads
- writes
- joins
- ordering
- filters

## Phase 6 — Code Relationship Graph

- persist entities
- persist relationships
- query graph

## Phase 7 — Vue Scanner

- components
- frontend API calls
- backend endpoint mapping

## Phase 8 — Python Scanner Cleanup

- normalize Python output

## Phase 9 — Generic Knowledge Synthesis

- business concept inference
- table-role inference
- Source of Truth candidates

## Phase 10 — Validator Upgrade

- validate structural relationships
- downgrade unsupported inference

## Phase 11 — project_lookup Enhancement

- return semantic + structural results

## Phase 12 — New Code Tools

- trace API
- trace table
- trace state

## Phase 13 — TASK-013 Regression

- existing ground-truth suite

## Phase 14 — Generic Second Project Test

- synthetic non-TASK-013 project

---

# 44. Recommended Commit Sequence

```text
01 refactor: remove task013 hardcoding from generic knowledge synthesis
02 feat: add project-local knowledge override loading
03 feat: add normalized code entity and relationship models
04 feat: add scanner adapter interface
05 feat: add java spring scanner
06 feat: add entity and orm mapping
07 feat: add mybatis mapper and xml scanner
08 feat: add sql table usage analysis
09 feat: add local code relationship graph
10 feat: add api-to-service-to-table tracing
11 feat: add table-to-code usage tracing
12 feat: add state and enum tracing
13 feat: add vue api usage scanner
14 refactor: normalize python scanner output
15 refactor: make knowledge synthesis project-agnostic
16 feat: upgrade blueprint validator with relationship evidence
17 feat: enhance project_lookup with code relationships
18 feat: add code graph read-only tools
19 test: add task013 regression suite
20 test: add generic non-task013 project bootstrap suite
21 docs: document generic project bootstrap architecture
```

---

# 45. Definition of Done

V0.3 is complete when:

- Generic Bootstrap contains no required TASK-013 business hardcoding.
- TASK-013-specific confirmed rules can live in project-local override data.
- Java/Spring controllers, services, repositories, entities and APIs are structurally detected.
- MyBatis mapper interfaces and XML statements are connected.
- SQL statements are mapped to database tables.
- Read/write table usage is identifiable through static analysis.
- API -> Controller -> Service -> Mapper/Repository -> Table chains can be reconstructed.
- Table -> code usage can be queried.
- State/enum definitions and major assignment sites can be queried.
- Vue frontend API calls can be linked to backend APIs where evidence exists.
- Python project scanning remains functional.
- Project Blueprint generation uses generic evidence rather than project-name rules.
- Source of Truth inference is evidence-based.
- Unsupported relationships are not marked confirmed.
- `project_lookup()` returns both business semantics and code relationships.
- TASK-013 regression accuracy does not decrease.
- A second non-TASK-013 industrial fixture can bootstrap successfully.
- No production write capability is introduced.

---

# 46. Final Design Principle

IRO_agent V0.3 should move from:

```text
Generic Scanner
    +
TASK-013 hardcoded meaning
```

to:

```text
Generic Structural Scanner
        |
        v
Code Relationship Graph
        |
        v
Database Schema
        |
        v
GLM Semantic Synthesis
        |
        v
Validated Project Blueprint
        |
        v
Optional Project Override
```

The target capability is:

> **Give IRO_agent an unfamiliar industrial software project, run `iro-agent init`, and let it learn the project's technical structure and business meaning without requiring TASK-013-specific code changes.**
