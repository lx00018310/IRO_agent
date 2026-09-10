# IRO_agent — WRelease Time-Axis Evidence Integrity Fix Plan

## 1. Goal

This plan updates the current IRO_agent implementation with a **dual version-provider architecture**.

IRO_agent must support two independent version-history tools:

```text
GitReader
WReleaseReader
```

They are parallel alternatives, not cumulative requirements.

For each configured project, IRO_agent must select exactly one active version provider:

```text
Git available
    -> use GitReader

Git unavailable / project does not use Git
    -> use WReleaseReader
```

The selection rule is:

> **Git first. WRelease fallback. One active version provider per project.**

All other evidence sources remain independent:

- application logs
- database timestamps
- incident records
- user questions
- conversation messages
- diagnostic conclusions

These sources are correlated through a unified chronological timeline together with the selected version provider.

---

# 2. Core Rules

## 2.1 GitReader and WReleaseReader are parallel version providers

IRO_agent must define a common abstraction:

```text
VersionReader
```

with two implementations:

```text
GitReader
WReleaseReader
```

The project configuration determines which reader is active.

Automatic default selection:

```text
if valid Git repository exists:
    active_version_reader = GitReader
else if valid WRelease source exists:
    active_version_reader = WReleaseReader
else:
    active_version_reader = None
```

Git has priority when both are configured and valid.

Do not use both readers simultaneously for one diagnostic flow unless a future project explicitly enables a special comparison mode.

V0.1 should keep selection simple and deterministic.

---

## 2.2 GitReader responsibilities

When GitReader is active, it is the authoritative version-history source.

It may provide:

```text
commit history
commit timestamp
changed files
diff
blame
branch / HEAD
tags
commit messages
```

GitReader should expose version events to the unified timeline.

Example:

```json
{
  "event_type": "version_change",
  "source_type": "git",
  "timestamp": "2026-09-10T09:28:03",
  "version_id": "abc123",
  "description": "fix order state transition"
}
```

---

## 2.3 WReleaseReader responsibilities

When Git is unavailable or the project is managed through WRelease, WReleaseReader becomes the authoritative version-history source.

It may provide:

```text
WRelease version
release/update time
module version
package/file information
update description
release records
confirmed running version when explicitly available
```

WRelease must not require Git mapping.

WReleaseReader should expose version events to the same unified timeline format.

---

## 2.4 Time is the common correlation layer

Regardless of whether the active version provider is GitReader or WReleaseReader, all evidence must preserve timestamps.

The diagnostic timeline may merge:

```text
Active Version Provider
+
Logs
+
Database
+
Conversation
+
Incident Memory
```

Example:

```text
2026-09-10 09:28:03
Version:
backend updated

2026-09-10 09:29:10
Log:
order processing timeout

2026-09-10 09:29:14
Database:
order remained in WAITING state

2026-09-10 09:31:22
User:
"为什么订单卡住了？"
```

---

# 3. Required Code Changes

## Phase 1 — Introduce VersionReader Selection

### Objective

Refactor version-history access so GitReader and WReleaseReader are two interchangeable providers.

### Required changes

Create a common interface or adapter layer:

```text
VersionReader
├─ GitReaderAdapter
└─ WReleaseReaderAdapter
```

Minimum common operations should include equivalents of:

```text
is_available()
get_current_version()
get_recent_versions()
get_version_events(start_time, end_time)
compare_versions(a, b)
get_version_details(version_id)
```

Exact method names may differ, but the orchestrator must not need to know whether the active source is Git or WRelease.

### Selection logic

Implement a resolver:

```text
VersionReaderResolver
```

Selection order:

```text
1. Check configured Git repository.
2. If Git repository is valid and readable -> select GitReader.
3. Otherwise check WRelease source.
4. If WRelease source is valid and readable -> select WReleaseReader.
5. Otherwise -> no version provider.
```

If both are valid:

```text
GitReader wins by default.
```

The selected provider must be visible through diagnostics/logging.

Example:

```text
Active version provider: GitReader
```

or:

```text
Active version provider: WReleaseReader
```

### Acceptance criteria

- A Git-based project uses GitReader only.
- A WRelease-only project uses WReleaseReader only.
- A project with both valid sources uses GitReader by default.
- A project with neither still allows non-version diagnosis using logs/database/memory.
- Diagnostic orchestration does not contain Git-specific or WRelease-specific branching beyond the resolver/adapter layer.

---

# 4. WReleaseReader Redesign

## 4.1 Responsibilities

WReleaseReader should focus only on facts that WRelease actually knows and expose them through the common VersionReader abstraction.

Minimum structured information:

```text
release/version id
release/update time
module
module version
package/file information
update description
release record
deployment/runtime status if explicitly available
```

Do not invent fields that do not exist in the actual TASK-013 WRelease data.

---

## 4.2 Separate three concepts

Do not mix:

```text
Latest Available Package
Latest Update Record
Confirmed Running Version
```

These are different.

Recommended structured output:

```json
{
  "latest_available_release": "...",
  "latest_update_record": "...",
  "confirmed_running_release": null,
  "running_release_source": "unknown"
}
```

If the running version cannot be verified:

```text
Confirmed Running Version: UNKNOWN
```

Do not substitute the latest package.

---

## 4.3 Update history

WReleaseReader must expose release/update records as time-stamped events.

Example:

```json
{
  "event_type": "wrelease_update",
  "timestamp": "2026-09-10T09:28:03",
  "version": "1.3.21",
  "module": "backend",
  "description": "..."
}
```

These events will later enter Incident Timeline.

---

# 5. GitReader Version Provider

GitReader should remain available as the preferred version provider when a valid Git repository exists.

Minimum capabilities:

```text
current branch / HEAD
recent commits
commit timestamps
changed files
diff
blame
tags when useful
```

GitReader should convert commit history into normalized version events.

Example:

```json
{
  "event_type": "version_change",
  "source_type": "git",
  "timestamp": "2026-09-10T09:20:00",
  "version_id": "abc123",
  "description": "update order state handling"
}
```

GitReader must remain read-only.

Do not expose arbitrary Git commands to the model.

Allowed operations should continue to be wrapped explicitly.

---

# 6. Unified Time Event Model

Create a common internal event structure.

Recommended model:

```text
TimelineEvent
├─ event_id
├─ project
├─ timestamp
├─ source_type
├─ source_id
├─ event_type
├─ title
├─ detail
├─ evidence_level
└─ metadata
```

Recommended `source_type` values:

```text
wrelease
log
database
conversation
incident
agent
```

Recommended `evidence_level` values:

```text
CONFIRMED
INFERRED
UNKNOWN
```

Do not use fake numeric confidence.

---

# 7. Conversation Time Recording

Every incoming and outgoing message must preserve its time.

For every user message record:

```text
message_id
session_id
user_id
project
timestamp
message_text
message_type
```

For every agent response record:

```text
message_id
session_id
timestamp
response_text
related_incident_id
```

The purpose is not only chat history.

Conversation messages must become evidence in the Incident Timeline.

Example:

```text
09:31:22 用户首次报告“订单卡住”
```

This makes it possible to answer:

```text
问题什么时候第一次被人发现？
```

---

# 8. Incident Timeline Rewrite

Incident Timeline should merge events from:

```text
Active VersionReader
+
LogReader
+
DatabaseReader
+
Conversation History
+
Incident Memory
```

`Active VersionReader` is either GitReader or WReleaseReader for the current project.

Recommended flow:

```text
user question
     |
     v
determine investigation time range
     |
     +-> Active VersionReader events
     +-> Log events
     +-> Database events
     +-> Conversation events
     +-> Previous incident events
     |
     v
normalize timestamps
     |
     v
sort chronologically
     |
     v
build Incident Timeline
```

---

# 9. Fault Domain Judgment Fix

Current logic must be corrected.

Rule:

```text
No evidence
!=
Mostly ruled out
```

Correct behavior:

```text
positive evidence
    -> High / Medium / Low

explicit negative evidence
    -> Mostly ruled out

no relevant evidence
    -> Insufficient evidence
```

Initial fault domains can remain:

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

Every non-Unknown judgment must reference evidence.

---

# 10. Impact Scope Judgment Fix

All impact states must default to:

```text
Unknown
```

Do not default any function to "Normal".

Allowed states:

```text
Affected
Normal
Unknown
```

Only mark:

```text
Normal
```

when actual evidence confirms normal behavior.

Only mark:

```text
Affected
```

when actual evidence supports the impact.

Example:

```text
New order creation: Affected
Existing order query: Unknown
PLC communication: Normal
Robot dispatch: Unknown
```

---

# 11. Incident Memory Completion

The diagnostic pipeline must write structured results into Incident Memory.

When a real incident is created or updated, persist:

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
related_git_commits
related_wrelease_versions
resolution_summary
similar_incident_ids
timeline_event_ids
active_version_provider
```

Only the active version-provider field should normally be populated:

```text
GitReader active
    -> related_git_commits populated
    -> related_wrelease_versions empty

WReleaseReader active
    -> related_wrelease_versions populated
    -> related_git_commits empty
```

---

# 12. Similar Historical Incident Statistics

Similarity search should use:

```text
symptom
fault_domain
root_cause
impact_scope
active version information
time proximity
text similarity
```

Version similarity must use whichever provider is active for the project.

Expected answer example:

```text
过去90天发现4起类似事件。

其中：
后端相关 2次
数据库相关 1次
WRelease更新后出现 1次

最近一次：
2026-09-02 14:18
```

Every count must come from actual Incident Memory records.

---

# 13. Diagnostic Orchestrator Update

The diagnostic flow should become:

```text
User Question
      |
      v
Conversation Timestamp
      |
      v
Incident / Query Classification
      |
      v
VersionReaderResolver
      |
      +----------------------+
      |                      |
      v                      v
GitReader                WReleaseReader
(use if valid)           (fallback)
      \                      /
       \                    /
        +--------+---------+
                 |
                 v
             LogReader
                 |
                 v
           DatabaseReader
                 |
                 v
       Historical Incidents
                 |
                 v
        Unified Time Events
                 |
                 v
         Incident Timeline
                 |
          +------+------+
          |             |
          v             v
    Fault Domain    Impact Scope
          \             /
           \           /
            v         v
         Evidence Summary
                 |
                 v
      Business Language Interpreter
                 |
                 v
               User
```

Only one of GitReader or WReleaseReader is active for a given project diagnosis.

---

# 14. Version Time-Correlation Logic

The agent must be able to answer:

```text
这个问题是在最近一次版本变化之前还是之后发生的？
```

The logic must be provider-independent.

### When GitReader is active

Use:

```text
commit timestamp
commit/change details
affected files/modules
```

### When WReleaseReader is active

Use:

```text
release/update timestamp
version/module details
package/update records
```

Correct logic:

1. Determine the first confirmed symptom/error time.
2. Query the active VersionReader for relevant version events.
3. Find version events immediately before and after the symptom.
4. Compare timestamps.
5. Check whether changed files/modules are plausibly related to the fault domain.
6. Describe temporal relationship only.

Allowed conclusions:

```text
Occurred before the version change
Occurred after the version change
Strong temporal relationship
Possible temporal relationship
No obvious temporal relationship
Insufficient evidence
```

Forbidden conclusion:

```text
The version change caused the issue
```

unless additional evidence supports causality.

Time correlation is not automatically causation.

---

# 15. Evidence Integrity Rules

Apply these rules throughout the codebase.

## Rule A

Unknown must remain unknown.

## Rule B

Latest package is not automatically the running version.

## Rule C

No evidence is not evidence of normal behavior.

## Rule D

No evidence is not evidence that a fault domain is ruled out.

## Rule E

Temporal correlation is not automatically causation.

## Rule F

Every confirmed event must have a source.

## Rule G

Every inferred event must be explicitly marked as inferred.

## Rule H

Version-provider selection must be explicit and deterministic:

```text
Git available -> GitReader
Git unavailable -> WReleaseReader
```

Do not silently combine both sources for one project diagnosis.

---

# 16. Tests to Modify

Remove or rewrite tests that assert:

```text
WRelease -> Git commit must exist
```

Replace them with tests such as:

### Test 1

WRelease package exists but running-version information does not exist.

Expected:

```text
confirmed_running_release = UNKNOWN
```

### Test 2

WRelease update occurs at 10:00 and first error occurs at 10:07.

Expected:

```text
error occurred after update
```

Do not assert:

```text
update caused error
```

### Test 3

No evidence exists for PLC.

Expected:

```text
PLC = Insufficient evidence
```

### Test 4

No evidence exists for historical-order query.

Expected:

```text
Historical order query = Unknown
```

not:

```text
Normal
```

### Test 5

Incident is created.

Expected structured memory fields include:

```text
fault_domain
impact_scope
WRelease version
timeline
```

### Test 6

Both Git and WRelease are configured and valid.

Expected:

```text
active_version_provider = GitReader
```

### Test 7

Git is invalid or absent, WRelease is valid.

Expected:

```text
active_version_provider = WReleaseReader
```

### Test 8

Neither Git nor WRelease is available.

Expected:

```text
active_version_provider = None
```

Diagnosis must still be able to use logs/database/memory where possible.

---

# 17. Five Real TASK-013 Blind Tests

After code changes, use five questions whose answers are already known by a human.

Do not merely print model answers.

Each test must contain:

```text
Question
Known Ground Truth
Required Evidence
Agent Answer
PASS / FAIL
```

Recommended questions:

## Q1

```text
今天更新了什么？
```

Ground truth must come from the active version provider.

## Q2

```text
这个异常发生在最近一次更新之前还是之后？
```

Ground truth must compare the active version event timestamp and first error timestamp.

## Q3

```text
这次问题最可能属于哪个故障域？
```

Ground truth must be manually confirmed.

## Q4

```text
以前出现过多少次类似问题？
```

Ground truth must come from Incident Memory.

## Q5

```text
这次异常目前确认影响哪些业务？
```

Ground truth must distinguish:

```text
Affected
Normal
Unknown
```

---

# 18. Scope Control

Do not add new features during this task.

Do not implement:

```text
CodeGraph expansion
Feishu Gateway
Dashboard
Automatic repair
New UI
simultaneous Git+WRelease diagnosis for one project
cross-provider reconciliation
```

The task is strictly an **Evidence Integrity + WRelease Time-Axis Fix**.

---

# 19. Recommended Commit Sequence

```text
01 refactor: introduce common version reader abstraction
02 feat: add version reader resolver with git-first selection
03 refactor: adapt git reader to version-provider interface
04 refactor: adapt wrelease reader to version-provider interface
05 feat: add unified timestamped evidence event model
06 feat: record conversation messages on diagnostic timeline
07 fix: correct fault-domain insufficient-evidence handling
08 fix: default impact scope to unknown
09 feat: persist structured diagnostic results to incident memory
10 refactor: make incident timeline consume active version provider
11 test: add version-provider selection tests
12 test: add provider-independent time-correlation tests
13 test: add five task013 ground-truth blind tests
```

---

# 20. Definition of Done

This fix is complete when:

- GitReader and WReleaseReader both implement the common version-provider contract.
- GitReader is automatically selected when a valid Git repository exists.
- WReleaseReader is automatically selected when Git is unavailable and WRelease is valid.
- Only one version provider is active for one project diagnosis.
- A project with neither version source can still use logs/database/memory.
- Version events from either provider are normalized into the same time-event structure.
- Conversation messages preserve timestamps.
- Logs preserve timestamps.
- Database evidence preserves timestamps when available.
- Incident Memory preserves timestamps.
- Incident Timeline merges all active evidence sources chronologically.
- Unknown running WRelease version remains UNKNOWN.
- Fault domains without evidence return `Insufficient evidence`.
- Impact states without evidence return `Unknown`.
- Structured diagnostic results are persisted to Incident Memory.
- Similar incident counts use real stored incidents.
- Five TASK-013 ground-truth blind tests produce explicit PASS/FAIL results.
- No unrelated features are added.

---

# 21. Final Design Principle

For every project:

```text
GitReader or WReleaseReader tells IRO_agent what version/change happened.
Logs tell IRO_agent what the system did.
Database tells IRO_agent what business state existed.
Conversation tells IRO_agent when humans observed the problem.
Incident Memory tells IRO_agent what happened before.
Time connects them together.
```

Version selection follows one rule:

```text
Git available
    -> GitReader

Git unavailable
    -> WReleaseReader
```

The rest of the diagnostic architecture remains identical regardless of which version provider is active.
