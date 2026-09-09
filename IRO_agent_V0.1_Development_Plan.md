# IRO_agent V0.1 — Development Plan

## 1. Project Goal

Build a command-line application named **IRO_agent** (**Industrial_Read_Only_Agent**).

The product is a strictly read-only AI diagnostic assistant for industrial software projects.

The first real validation target is:

**TASK-013**

The application must help non-technical users, project managers, field engineers, and developers understand failures through natural-language questions.

The agent must be able to:

- Receive questions through **WeChat Gateway** as the highest-priority external entry point.
- Provide a local command-line chat/configuration interface for development, testing, and administration.
- Use **GLM-5.3-Flash** as the primary model.
- Read source code, Git history, WRelease deployment information, logs, and production database data.
- Build and maintain its own incident memory.
- Explain technical conclusions in business language.
- Build incident timelines.
- Judge the most likely fault domain.
- Judge impact scope and severity.
- Count and summarize similar historical incidents.
- Accept images directly through GLM-5.3-Flash multimodal capability.
- Never modify production code, configuration, database data, devices, services, or Git repositories.

The product is conceptually similar to a highly restricted Hermes Agent, but optimized for industrial diagnostics and evidence-based root-cause investigation.

---

# 2. Core Product Principle

The system must follow this rule:

> **Read, search, analyze, remember, explain — never modify production systems.**

The agent may write only to its own internal databases and audit records.

All production-facing tools must be read-only at the permission level, not merely through prompts.

---

# 3. Real Validation Project

## 3.1 Validation Target

Use **TASK-013** as the only mandatory real-world validation project for V0.1.

TASK-013 contains multiple frontend/backend and related application modules.

Its release process uses **WRelease** to package and deploy modules.

Therefore, source-code history and actual deployed-version history must be treated as two separate evidence sources.

---

## 3.2 Required Parallel Version Readers

The system must implement both:

### GitReader

Responsible for understanding:

- source commits
- diffs
- blame
- code history
- branch / HEAD
- modification time
- changed files
- commit relationships

### WReleaseReader

Responsible for understanding:

- actual release versions
- deployment time
- released modules
- package contents
- deployment environment
- file/module versions
- release records
- mapping between WRelease packages and Git commits when possible

These two readers must operate in parallel.

Key distinction:

> **GitReader tells the agent what changed in source code.**

> **WReleaseReader tells the agent what was actually deployed to the field system.**

The agent must never assume that the newest Git commit is the version currently running in production.

---

# 4. Initial Architecture

```text
                  WeChat Gateway
                       |
                       v
               Agent Orchestrator
                       |
                GLM-5.3-Flash
                       |
       +---------------+----------------+
       |               |                |
       v               v                v
   CodeReader       LogReader      DatabaseReader
       |
   CodeGraph
       |
  +----+----------+
  |               |
  v               v
GitReader     WReleaseReader
  \               /
   \             /
    v           v
      Incident Memory
            |
   +--------+----------+
   |        |          |
   v        v          v
Timeline  FaultDomain  SimilarIncidentStats
   \        |          /
    \       |         /
     +------v--------+
        ImpactScope
            |
            v
 Business Language Interpreter
            |
            v
          User
```

---

# 5. Technology Direction

The implementation should reuse existing open-source components where practical.

Preferred reference architecture:

- **Hermes Agent**: gateway, agent loop, memory concepts, provider/tool architecture
- **CodeGraph**: code dependency and call-graph understanding
- **HolmesGPT**: incident/RCA design concepts
- **rag-rat**: read-only source and provenance design concepts

Do not copy unnecessary framework complexity.

The final product should remain small and maintainable.

Recommended implementation choices:

- Python for core agent/backend
- SQLite for local incident memory and audit data
- GLM-5.3-Flash API
- Command-line interface only for V0.1
- Run as a long-lived local/background process when Gateway mode is enabled
- CodeGraph integration for structured code understanding

Do not build a desktop GUI in V0.1. The product should run directly from the command line and support Gateway operation as a long-lived process.

---

# 6. User-Facing Functions

V0.1 should expose only two interaction modes:

## 6.1 Gateway Mode

Primary production-facing interaction.

Users interact with the agent through WeChat Gateway.

The local process runs continuously and handles incoming Gateway messages.

Example:

```text
iro-agent gateway start
```

Required behavior:

- start Gateway listeners
- load project configuration
- initialize read-only tools
- initialize GLM-5.3-Flash
- maintain incident memory
- write audit logs
- remain operational without any CLI

## 6.2 CLI Mode

Used for:

- local testing
- administration
- configuration
- direct diagnostic chat
- checking Gateway status
- inspecting registered projects
- validating reader connectivity

Example commands:

```text
iro-agent chat
iro-agent config
iro-agent doctor
iro-agent gateway start
iro-agent gateway status
```

The CLI must remain simple.

No desktop GUI is required.

---

# 7. Required Agent Capabilities

## 7.1 WeChat Gateway

This is a **P0 feature** and must be implemented before Feishu.

Required behavior:

```text
WeChat Group
    |
User @Agent
    |
Gateway receives message
    |
Agent resolves project/context
    |
Agent performs read-only investigation
    |
Agent generates response
    |
Gateway replies to group
```

Requirements:

- respond only when explicitly addressed or when configured to do so
- preserve conversation/session context
- support text
- support images
- support multi-turn follow-up
- map group/session to project
- record incoming question and outgoing answer in internal audit history
- never expose secrets in replies

Feishu is explicitly deferred until after WeChat works reliably.

---

# 8. Read-Only Tool Layer

The agent must not receive unrestricted terminal, shell, browser, file-write, Git-write, database-write, or arbitrary HTTP tools.

Only explicitly defined tools may be registered.

---

## 8.1 CodeReader

Functions:

- search_code
- read_code
- locate_symbol

Permissions:

- read-only
- restricted to configured directories

Forbidden:

- write
- delete
- rename
- patch
- chmod
- execute

---

## 8.2 CodeGraph Integration

Use CodeGraph to support:

- symbol relationships
- callers
- callees
- dependency analysis
- impact analysis
- module relationships
- Java/Spring code understanding

CodeGraph must remain an analysis source only.

It must never gain permission to modify source files.

---

## 8.3 GitReader

Allowed operations:

- git log
- git show
- git diff
- git blame
- git status
- branch/head inspection
- tag inspection

Forbidden operations include:

- commit
- checkout
- reset
- merge
- rebase
- cherry-pick
- pull
- push
- fetch if not explicitly needed
- clean
- stash modification operations

Preferred implementation:

Do not expose a raw `git` command tool to the model.

Wrap specific read-only Git operations in code.

---

## 8.4 WReleaseReader

WReleaseReader is a first-class component.

It must not be implemented as an extension of GitReader.

Minimum responsibilities:

- discover available WRelease versions
- identify current deployed version when the information is available
- parse release/package metadata
- identify modules contained in each release
- obtain release timestamps
- compare two WRelease versions
- identify changed modules/files
- map WRelease module/package versions to Git commits when possible
- provide structured release evidence to the agent

Example structured output:

```json
{
  "release_id": "20260909_1432",
  "timestamp": "2026-09-09T14:32:00",
  "environment": "production",
  "modules": [
    {
      "name": "backend",
      "version": "1.3.21",
      "git_commit": "abc123"
    }
  ]
}
```

The exact TASK-013 WRelease format must be reverse-engineered from the actual repository and release artifacts during implementation.

Do not invent metadata fields that do not exist.

---

## 8.5 LogReader

Required functions:

- search by time range
- search by keyword
- search by component
- search by error level
- retrieve surrounding lines
- correlate events across multiple log files when timestamps permit

LogReader must support TASK-013's actual log structure.

Large logs must be processed locally before relevant excerpts are sent to GLM.

---

## 8.6 DatabaseReader

Database access must be enforced as read-only at two levels.

### Level 1 — Database Permission

Use a database account that has only read privileges.

### Level 2 — Application Guard

Only allow safe query forms.

At minimum:

Allowed:

- SELECT
- WITH ... SELECT
- EXPLAIN SELECT if needed

Forbidden:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- TRUNCATE
- CALL
- GRANT
- REVOKE
- transaction commands that could modify data

Do not rely on prompting alone.

The model must never receive raw database passwords.

---

# 9. Incident Memory

The agent must maintain an internal incident database.

This is the only major writable system component.

Recommended storage:

**SQLite**

Minimum incident fields:

```text
incident_id
project
created_at
updated_at
status
symptom
user_question
fault_domain
root_cause
impact_scope
severity
confidence
related_logs
related_files
related_git_commits
related_wrelease_versions
resolution_summary
similar_incident_ids
```

Do not force root cause or resolution when evidence is insufficient.

Unknown values must remain unknown rather than hallucinated.

---

# 10. Incident Timeline

For each investigated incident, build a timeline where evidence allows.

Possible timeline sources:

- WRelease deployment records
- logs
- user report time
- database timestamps
- service startup logs
- Git commits
- previous incident records

Example:

```text
09:15 System operating normally
09:42 WRelease 1.3.21 deployed
09:48 Backend module restarted
10:03 First database timeout
10:07 First failed order
10:11 User reported issue in WeChat
10:22 Service recovered
```

Requirements:

- every timeline item should retain evidence/provenance
- distinguish confirmed events from inferred events
- do not fabricate missing timestamps
- timeline should be queryable later

---

# 11. Fault Domain Judgment

The agent must classify likely fault domains.

Initial TASK-013 domain list:

```text
Frontend
Backend
Database
Network
Device
Robot
PLC
Android
WRelease
Configuration
Third-party Interface
Unknown
```

Output should avoid fake precision.

Preferred result:

```text
Backend: High
Database: Medium
Network: Low
Frontend: Mostly ruled out
```

Allowed confidence labels:

- High
- Medium
- Low
- Mostly ruled out
- Insufficient evidence

The agent must include the evidence used for the classification.

---

# 12. Impact Scope Judgment

The agent must determine what business functions are affected.

Example:

```text
New order creation: Affected
Existing order query: Normal
Robot dispatch: Normal
Historical data query: Normal
```

Severity levels:

| Level | Meaning |
|---|---|
| P0 | Whole system or production stopped |
| P1 | Core business function unavailable |
| P2 | Partial function abnormal |
| P3 | Minor issue, main workflow unaffected |

Severity should be derived from evidence and business impact, not from technical error type alone.

---

# 13. Similar Historical Incident Statistics

The agent must support questions such as:

- Has this happened before?
- How many similar incidents occurred?
- When was the last one?
- What were the previous causes?
- Were previous cases related to releases?

Minimum behavior:

- search similar incidents
- count matches
- summarize causes
- show most recent similar incident
- identify repeated patterns when evidence supports them

Example:

```text
Past 90 days: 5 similar incidents

Database connection: 3
Post-release configuration: 1
Network: 1

Most recent similar incident:
2026-08-26
```

Similarity should initially use structured fields plus text search.

Do not introduce vector databases unless real validation shows SQLite/FTS is insufficient.

---

# 14. Business Language Interpreter

The final response must be understandable to users who do not know code.

The agent may internally reason using:

- file names
- stack traces
- SQL
- class names
- API routes
- commit hashes

But the main answer must translate those findings into business language.

Default answer structure:

```text
Conclusion

Impact

Evidence

Historical Similar Cases

Recommended Checks

Confidence
```

Example:

```text
Current judgment:

The issue is most likely in the order backend service rather than the frontend or robot.

Impact:
New order processing is affected.
Existing order lookup appears normal.

Evidence:
1. Backend errors began after today's WRelease deployment.
2. Database timeout errors started 6 minutes later.
3. Robot communication remains normal.

History:
Three similar incidents were found in the past 90 days.

Recommended checks:
Check today's backend deployment and database connection configuration first.

Confidence:
High
```

Technical details may be shown in a secondary evidence section when useful.

---

# 15. Multimodal Input

Do not build a separate image-diagnosis subsystem.

GLM-5.3-Flash already supports multimodal input.

Required flow:

```text
WeChat/CLI image
        |
        v
Input adapter
        |
        v
GLM-5.3-Flash
        |
        v
Normal diagnostic workflow
```

The agent may use image content together with:

- code
- logs
- releases
- database evidence
- incident history

No independent OCR subsystem is required in V0.1.

---

# 16. Security Requirements

Security is a hard requirement.

## 16.1 Production Systems Must Be Read-Only

The agent must not be able to:

- modify files
- write code
- edit configuration
- execute arbitrary shell commands
- restart services
- control PLC
- control robots
- modify database records
- modify Git
- deploy WRelease packages
- upload arbitrary code to production

---

## 16.2 Credential Security

Secrets must never be stored in plain-text application configuration when avoidable.

Preferred Windows mechanisms:

- Windows Credential Manager
- DPAPI

The model must receive only the result of authenticated operations.

It must never receive:

- database password
- GLM API secret
- WeChat secret
- tokens
- private keys

---

## 16.3 Secret Redaction

Before code, log, configuration, or database content is sent to GLM, redact likely secrets.

At minimum detect:

- password
- passwd
- secret
- token
- api_key
- private_key
- connection strings containing credentials
- PEM/private key blocks

The redaction layer must operate before model context construction.

---

## 16.4 Directory Allowlist

The application may read only configured paths.

Example:

```text
D:\TASK-013\
D:\TASK-013\logs\
D:\WRelease\
```

Any path outside the allowlist must be rejected.

---

## 16.5 Network Allowlist

Do not provide arbitrary internet access.

Allow only required network destinations such as:

- GLM API
- WeChat Gateway endpoints
- explicitly configured production read-only database endpoints

---

# 17. Audit Log

Every tool call should produce an internal audit record.

Minimum fields:

```text
timestamp
session_id
user
tool
operation
target
result_summary
success/failure
```

Do not store raw secrets.

Audit records are internal and writable.

This will make it possible to prove that the agent remained read-only.

---

# 18. Explicit Non-Goals

Do not implement the following in V0.1:

- automatic code modification
- automatic bug fixing
- shell / terminal access
- production service restart
- device control
- PLC control
- robot control
- Git write operations
- WRelease deployment
- database writes
- independent OCR pipeline
- independent image-diagnosis engine
- attachment-analysis platform
- Decision Memory
- requirement traceability
- responsibility/person tracking
- health dashboard
- desktop GUI
- Electron UI
- PySide UI
- Windows EXE packaging
- installer packaging
- advanced analytics dashboard
- autonomous remediation
- arbitrary web browsing
- arbitrary MCP tools
- Feishu Gateway before WeChat is stable
- Kubernetes
- Kafka
- Redis
- Milvus
- Elasticsearch
- unnecessary microservices

Keep V0.1 small.

---

# 19. Development Phases

## Phase 0 — Repository Investigation

Goal:

Understand TASK-013 and WRelease before implementing abstractions.

Tasks:

1. Inspect TASK-013 repository structure.
2. Identify frontend/backend/module boundaries.
3. Identify actual log locations and formats.
4. Identify database type and relevant schema.
5. Inspect Git history structure.
6. Inspect WRelease code/configuration/package format.
7. Determine how WRelease identifies versions.
8. Determine whether WRelease records Git commit hashes.
9. Determine how currently deployed versions can be identified.
10. Produce a short architecture note before coding.

Acceptance criteria:

- No guessed WRelease design.
- Real TASK-013 evidence is documented.
- Required reader interfaces are adjusted to match reality.

---

## Phase 1 — Security Skeleton

Goal:

Create the application with hard read-only boundaries before adding intelligence.

Implement:

- configuration model
- allowed path policy
- credential abstraction
- secret redaction
- audit log
- restricted tool registry
- no terminal/shell/write tools

Acceptance tests:

1. Attempt file modification → rejected.
2. Attempt path traversal → rejected.
3. Attempt Git commit → unavailable.
4. Attempt DB update → rejected.
5. Attempt arbitrary shell → tool does not exist.
6. Secret in config/log → redacted before model call.

---

## Phase 2 — TASK-013 Code and Git Readers

Implement:

- CodeReader
- CodeGraph adapter
- GitReader

Validate with real TASK-013 questions.

Acceptance questions:

- Where is order creation implemented?
- Which files control a specific known function?
- What changed in this module recently?
- Which commit changed this behavior?
- Which code paths may be impacted by this change?

Every answer must include evidence.

---

## Phase 3 — WReleaseReader

This is a critical TASK-013-specific phase.

Implement:

- WRelease discovery
- version parsing
- module parsing
- release timestamps
- release comparison
- current-version discovery when possible
- Git mapping when possible

Acceptance questions:

- What version is currently deployed?
- What was deployed today?
- Which modules changed?
- What changed between release A and B?
- Which Git commit corresponds to the deployed backend?
- Did the incident start before or after the release?

If WRelease does not expose a requested fact, answer "unknown" rather than inferring it.

---

## Phase 4 — LogReader

Implement real TASK-013 log support.

Required:

- time-window search
- keyword search
- error search
- context lines
- multi-log correlation

Acceptance questions:

- What errors occurred around 10:00?
- What happened immediately before the failure?
- Which module first reported an error?
- Was the system healthy before the WRelease deployment?

---

## Phase 5 — Incident Memory

Implement SQLite incident storage.

Required:

- create incident
- update incident
- search incidents
- link Git commits
- link WRelease versions
- link log evidence
- similar incident search
- similar incident count

Acceptance:

- repeated issue can find prior cases
- count is reproducible
- historical evidence is traceable
- new chats can reuse old incident knowledge

---

## Phase 6 — Incident Timeline

Implement automatic timeline construction.

Sources:

- user report
- WRelease
- logs
- DB timestamps when applicable
- Git
- prior incident records

Acceptance:

For a known TASK-013 issue, produce a chronological timeline with evidence for every item.

---

## Phase 7 — Fault Domain + Impact Scope

Implement structured diagnostic output.

Fault domains:

- Frontend
- Backend
- Database
- Network
- Device
- Robot
- PLC
- Android
- WRelease
- Configuration
- Third-party Interface
- Unknown

Impact severity:

- P0
- P1
- P2
- P3

Acceptance:

For each validation incident:

- identify likely domain
- identify affected functions
- identify unaffected functions where evidence exists
- avoid fake certainty
- cite evidence

---

## Phase 8 — Business Language Interpreter

Implement final answer transformation.

The final response should be concise and understandable.

Default format:

1. Conclusion
2. Impact
3. Evidence
4. Historical Similar Cases
5. Recommended Checks
6. Confidence

Acceptance:

A non-programmer should understand the answer without knowing:

- Java
- Vue
- SQL
- stack traces
- Git
- HTTP internals

Technical evidence may remain available below the summary.

---

## Phase 9 — GLM-5.3-Flash Integration

Implement:

- API configuration
- model invocation
- tool calling
- text input
- image input
- context construction
- evidence injection
- secret-safe context

Acceptance:

- normal text diagnosis works
- image-based questions work through GLM multimodal input
- tool calls remain limited to allowed read-only tools
- no secret appears in model context logs

---

## Phase 10 — WeChat Gateway

This is the highest-priority gateway.

Implement before Feishu.

Required:

- group @ handling
- direct question handling if configured
- session continuity
- text support
- image support
- reply delivery
- project mapping
- audit logging
- error handling

Acceptance scenarios:

1. User @Agent asks a simple TASK-013 question.
2. User asks a follow-up without repeating full context.
3. User sends an image and asks what it means.
4. Agent searches logs/release/code/history.
5. Agent replies in business language.
6. Agent does not leak secrets.
7. Multiple conversations do not mix context incorrectly.

---

## Phase 11 — CLI Interface

Implement a minimal command-line interface.

Required commands:

```text
iro-agent chat
iro-agent config
iro-agent doctor
iro-agent gateway start
iro-agent gateway status
```

Required capabilities:

- local chat for debugging
- project selection
- configuration editing
- connectivity checks
- security-policy checks
- Gateway start/status commands

Acceptance:

A user can configure TASK-013, verify dependencies, start the WeChat Gateway, and run a local diagnostic conversation entirely from the command line.

---

## Phase 12 — Runtime and Service Operation

The agent should run directly from the command line.

Required:

- clean startup
- configuration persistence
- protected credentials
- local log directory
- incident database persistence
- Gateway long-running mode
- graceful shutdown
- restart-safe state
- clear startup diagnostics

Optional later deployment methods may include:

- Windows Task Scheduler
- WinSW
- NSSM
- systemd on Linux

These are deployment options, not core V0.1 product requirements.

Do not build an EXE installer or desktop application in V0.1.

---

# 20. TASK-013 Validation Scenarios

The following scenarios must be tested using real TASK-013 data wherever possible.

## Scenario A — "It worked yesterday. Why is it broken today?"

Agent should inspect:

- WRelease history
- Git history
- logs
- relevant code
- previous incidents

Expected output:

- likely cause
- release relationship
- fault domain
- impact scope
- historical similar incident count
- evidence

---

## Scenario B — "Did today's upgrade cause this?"

Agent should compare:

- incident start time
- WRelease deployment time
- first error time
- affected modules
- corresponding Git changes

Expected:

A conclusion such as:

- strongly related
- possibly related
- no evidence of relation
- insufficient evidence

Do not automatically blame the newest release.

---

## Scenario C — "Has this happened before?"

Expected:

- similar incident count
- recent examples
- previous root causes
- previous WRelease/Git relationships

---

## Scenario D — "Which part of the system is broken?"

Expected:

Fault-domain judgment using:

- High
- Medium
- Low
- Mostly ruled out
- Insufficient evidence

---

## Scenario E — "Can we keep using the system?"

Expected:

- affected functions
- unaffected functions
- P0/P1/P2/P3 level
- recommended human checks

Agent must not execute recovery actions.

---

## Scenario F — "What happened from beginning to end?"

Expected:

Incident Timeline with evidence.

---

## Scenario G — Image Question

User sends a screenshot/photo through WeChat.

Expected:

- image passed to GLM-5.3-Flash
- image interpretation combined with normal diagnostic sources
- no separate OCR service required

---

# 21. Answer Quality Rules

Every diagnostic answer must follow these rules:

1. Do not claim a root cause without evidence.
2. Separate facts from inference.
3. Prefer "insufficient evidence" over guessing.
4. Do not invent WRelease/Git relationships.
5. Do not invent historical incidents.
6. Do not fabricate timestamps.
7. Do not expose passwords, keys, tokens, or secrets.
8. Explain in business language first.
9. Keep technical evidence traceable.
10. State confidence qualitatively.

---

# 22. Definition of Done for V0.1

V0.1 is complete only when all of the following are true:

- TASK-013 can be configured.
- GLM-5.3-Flash is operational.
- WeChat Gateway is operational.
- CodeReader is operational.
- CodeGraph integration is operational.
- GitReader is operational.
- WReleaseReader is operational.
- LogReader is operational.
- DatabaseReader is read-only and operational.
- Incident Memory persists across sessions.
- Incident Timeline works.
- Fault Domain Judgment works.
- Impact Scope Judgment works.
- Similar Historical Incident Statistics work.
- Business Language Interpreter works.
- Images can be handled through GLM-5.3-Flash.
- CLI chat and configuration commands work.
- CLI startup and Gateway long-running mode work.
- Secrets do not enter model context.
- Production source code cannot be modified.
- Production database cannot be modified.
- Git repository cannot be modified.
- No arbitrary shell execution exists.
- All tool usage is auditable.

---

# 23. Implementation Rule for Local AI

When executing this plan:

1. Prefer minimum-change implementation.
2. Reuse mature open-source components where practical.
3. Do not over-engineer.
4. Do not add features outside this plan.
5. Do not redesign TASK-013.
6. Do not modify TASK-013 production behavior.
7. Treat TASK-013 as read-only validation data.
8. Investigate real WRelease behavior before implementing WReleaseReader.
9. Complete one phase and its tests before moving to the next.
10. Keep commits small and phase-specific.
11. Record all assumptions.
12. If evidence is missing, mark it explicitly instead of inventing behavior.
13. Security restrictions must be implemented in code and permissions, not only prompts.

---

# 24. Recommended Commit Sequence

```text
01 chore: initialize IRO_agent
02 feat: add security policy and restricted tool registry
03 feat: add task013 code reader
04 feat: add read-only git reader
05 feat: integrate codegraph
06 feat: add wrelease reader
07 feat: add task013 log reader
08 feat: add read-only database reader
09 feat: add incident memory
10 feat: add incident timeline
11 feat: add fault-domain classification
12 feat: add impact-scope classification
13 feat: add similar-incident statistics
14 feat: add business-language response layer
15 feat: integrate glm-5.3-flash
16 feat: add wechat gateway
17 feat: add cli chat and configuration commands
18 feat: add gateway runtime and health-check commands
19 test: add task013 end-to-end validation suite
20 docs: finalize security and runtime guide
```

---

# 25. Final Product Statement

The completed V0.1 should be demonstrable with this scenario:

> A non-technical TASK-013 user asks in a WeChat group:
>
> "Why are orders stuck again today? Did the upgrade just now cause this?"

The agent should automatically investigate:

- current and recent WRelease deployments
- relevant Git changes
- TASK-013 code
- logs
- read-only database state
- historical incidents

Then answer in plain business language with:

- conclusion
- impact
- evidence
- incident timeline
- likely fault domain
- similar historical incident count
- recommended human checks
- confidence

While maintaining a strict guarantee at the system-permission level that the agent cannot modify the production project.
