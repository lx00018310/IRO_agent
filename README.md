# IRO_agent — Industrial Read-Only Agent

> **English** · [中文文档](readme_cn.md)

> **IRO_agent is an evidence-driven, strictly read-only diagnostic AI agent for industrial software systems.** It learns a project's operational model, investigates incidents through iterative evidence gathering, and scores the quality of its own diagnosis using reproducible evaluation datasets.

[![Tests](https://img.shields.io/badge/tests-338%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Security](https://img.shields.io/badge/boundary-Strict%20Read--Only-red.svg)]()

---

## What is IRO_agent?

**IRO_agent** (Industrial Read-Only Agent) is an AI agent harness for diagnosing incidents in industrial software systems — such as scheduling systems, production databases, and service logs. Unlike a general-purpose chat assistant, it never reasons from fixed, one-shot steps. Instead, it runs three closed-loop, industrial-grade **harnesses** that work together:

- **Project Learning Harness** — builds a model of *what the system actually is*.
- **Investigation Harness** — gathers evidence and re-plans every round to find *what actually went wrong*.
- **Evaluation Harness** — grades the diagnosis itself so that quality is *measurable and reproducible*.

Every finding must be anchored to concrete evidence (a log line, a configuration key, a database row), and every tool is **strictly read-only** against the system being diagnosed.

| Quick fact | Value |
| :--- | :--- |
| **What it is** | An evidence-driven, strictly read-only industrial diagnostic agent |
| **Category** | AI agent / industrial diagnostics / site reliability / incident investigation |
| **Package name** | `iro-agent` (installable via `pip install -e .`) |
| **Entry point** | `python -m iro_agent.cli` |
| **Python** | `>= 3.10` |
| **License** | MIT |
| **Safety boundary** | Strict read-only — no file writes, no Git commits, no business-database writes, no arbitrary shell |

---

## Who is it for?

IRO_agent is designed for teams operating industrial and on-premise software in production:

- **Plant / operations engineers** who need to triage scheduling systems, databases, and service logs under noisy, high-concurrency conditions.
- **Industrial software maintainers** working on scheduling dispatchers (e.g. WES), ERP/backend services, and machine or device data flows.
- **On-premise / air-gapped deployments** where the environment may lack standard Python tooling (a single-file `uv.exe` path is provided).
- **QA and reliability teams** who need a reproducible, evidence-anchored way to evaluate diagnostic quality.

---

## Key capabilities

- **Strict Read-Only safety** — no writes, Git commits, business-database writes, or arbitrary shell execution against the diagnosed system.
- **Evidence provenance** — every inference must be bound to a specific log line, config key, or database record; guessing is prohibited.
- **Per-round dynamic re-planning** — each investigation round re-decides the next action based on the latest evidence instead of following a fixed script.
- **Competing-hypothesis lifecycle** — 2–5 hypotheses are generated, then added, refined, merged, or discarded across the investigation.
- **Observability-gap awareness** — timeouts and disconnections are correctly classified as `OBSERVABILITY_GAP` rather than mislabeled as a hardware fault.
- **Knowledge modeling of unknowns** — business-flow blind spots, hardware-interaction uncertainty, and config drift are modeled as first-class `KnowledgeUnknown` objects.
- **Reproducible evaluation** — deterministic, evidence-grounding, safety, and path-quality graders rate each diagnosis in an objective way.

---

## How it works

| Project Learning Harness | Investigation Harness | Evaluation Harness |
| :--- | :--- | :--- |
| • `Unknown` as a first-class object | • Per-round dynamic re-planning | • Production-identical dispatcher |
| • 10-dimension coverage tracking | • Competing-hypothesis lifecycle state machine | • Deterministic graders |
| • Multi-round iterative code reading | • Fact vs. cause decoupling | • Evidence-anchoring scoring |
| • Confidence calibration & anti-pollution | • Read-only tool hard-gate | • DEV / REGRESSION datasets |

1. **Learn** — the Project Learning Harness bootstraps a project model from source code, config, database schema, and logs.
2. **Investigate** — the Investigation Harness gathers evidence round by round, tests competing hypotheses, and pinpoints the root cause.
3. **Evaluate** — the Evaluation Harness replays every diagnosis and grades it with objective, deterministic graders.

---

## Core design principles

Industrial diagnosis is fundamentally different from ordinary conversational assistants: industrial triage faces high-concurrency log noise, subjective user misdirection, timing coincidences, and counter-intuitive scenarios such as physical power loss or network disconnects. IRO_agent abandons the traditional "one-shot fixed-step checklist" and instead evolves into three closed-loop harnesses:

1. **Strict Read-Only safety hard-gate** — the diagnosed system is never written to, never committed via Git, and never written to business databases; diagnostic tools provide no arbitrary shell execution. The configuration wizard only saves IRO's own configuration, while internal auditing, memory, and cognitive cache remain managed by IRO. Dual-layer read-only interception plus redacted auditing keeps the production safety baseline intact.
2. **Evidence provenance (no evidence, no claim)** — every inference must be anchored to a concrete log line, configuration key, or database record; speculation without basis is forbidden.
3. **Physical vs. digital boundary** — when digital observation is sufficient and shows no anomaly, a legitimate on-site physical escalation is supported, avoiding the trap of blindly labeling an observation gap as a hardware fault.

---

## Core subsystem architecture

### 1. Investigation Harness (per-round dynamic re-planning)

- **Unified runtime dispatcher (`RuntimeDispatcher`)** — normalizes the Feishu gateway, CLI diagnostic sessions, direct investigation commands, and benchmark evaluation so that any fault is forced through the Harness.
- **Per-round re-planning engine (`LLMInvestigationPlanner`)** — re-invokes the LLM each round based on the latest dynamic evidence; a fixed one-way step flow is prohibited.
- **Permission & schema hard-gate (`PlannerValidator`)** — strictly validates the JSON schema, the read-only tool allow-list, the input models, and the step budget; illegal operations are physically blocked.
- **Competing-hypothesis lifecycle (`HypothesisManager`)** — supports first-round generation of 2–5 hypotheses and the full lifecycle of adding, deleting, editing, merging, and discarding them.
- **Fact vs. cause decoupling (`EvidenceEvaluator`)** — separates evidence fact extraction from root-cause inference; timeouts and disconnects are correctly identified as `OBSERVABILITY_GAP`.

### 2. Project Learning Harness

- **`Unknown` as a first-class object (`KnowledgeUnknown`)** — explicitly models business-flow blind spots, hardware-interaction uncertainty, and configuration differences.
- **Multi-dimensional coverage (`LearningState`)** — spans 10 dimensions including architecture, modules, business flows, state machines, and golden-source databases, and advances autonomously by coverage benefit and priority.
- **Anti-pollution memory mechanism** — historical experience is strictly treated as a prior reference (`prior_bias_only`) and is forbidden from being used directly as current root-cause evidence.

### 3. Evaluation Harness

- **Multi-dimensional metrics** — case pass rate, root-cause accuracy, evidence-anchoring score, path quality, and safety-violation monitoring.
- **Layered grader system**:
  - `DeterministicGrader` — strictly verifies root-cause classification, responsibility boundaries, and key keywords.
  - `EvidenceGroundingGrader` — verifies that every conclusion claim is traceable to real tool-observation records.
  - `SafetyGrader` — detects any write attempt, destructive instruction, or sensitive-data leak.
  - `PathQualityGrader` — evaluates exploration efficiency and detects dead loops and ineffective probes.
- **Strict anti-cheat rules** — see [docs/evaluation_policy.md](docs/evaluation_policy.md). Reading ground truth, prompt special-casing, and implicit test-mode score padding are all prohibited.

---

## Dataset layering

| Dataset | Directory | Purpose |
| :--- | :--- | :--- |
| **DEV Dataset** | `evaluation_cases/dev/` | For algorithm development and AI prompt engineering iteration; includes 20+ real industrial scenarios and edge cases. |
| **REGRESSION Dataset** | `evaluation_cases/regression/` | Quality gate set; includes 5 counter-intuitive cases, safety defense, and historical-defect cases. |
| **BLIND Dataset** | external private directory (may never be committed) | Production-grade blind test set, fully invisible during development, used for final admission/exit validation. |

---

## Quick start & deployment

### 1. Installation & dependencies

Choose one of the following based on the on-site industrial PC environment:

#### Option A: native Python (for environments with standard Python installed)

```bash
# 1. Create a virtual environment (Python 3.10+ recommended)
python -m venv .venv

# 2. Activate the virtual environment
# Git Bash:
source .venv/Scripts/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

# 3. Install project dependencies
pip install -e .
```

#### Option B: single-file `uv.exe` (recommended for on-site embedded minimal Python / offline environments)

> If the industrial site uses the `embed-amd64` minimal Python (which by default lacks the `venv` and `pip` modules), a single-file, installation-free `uv.exe` avoids the missing-Python-environment problem.

- **Online industrial PC, one-command install**:
  ```bash
  # Download and add to the current session PATH
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  export PATH="$HOME/.local/bin:$PATH"

  # Create the virtual environment and install dependencies
  uv venv .venv
  source .venv/Scripts/activate
  uv pip install -e .
  ```

- **Offline intranet industrial PC (copy a single file directly)**:
  Copy a single downloaded [`uv.exe`](https://github.com/astral-sh/uv/releases) to the project root, then run:
  ```bash
  ./uv.exe venv .venv
  source .venv/Scripts/activate
  ./uv.exe pip install -e .
  ```

#### Dynamic web-probe kernel installation (for WES / dispatcher dynamic page scraping)

If the site needs `web_fetch` to scrape and inspect dispatcher-system web pages (dynamic async pages such as DevExpress Blazor Server, Vue, React, ASP.NET WebForms), Playwright depends on a separate Chromium runtime and requires the official download command:

```bash
# Download and install the Chromium browser kernel
playwright install chromium
```

> [!TIP]
> **Intranet / weak-network download acceleration**: if the on-site PC accesses overseas sources slowly, you can point to a China mirror before downloading:
> ```powershell
> # Windows PowerShell:
> $env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"
> playwright install chromium
> ```

### 2. First run: complete the project configuration wizard (required)

One IRO_agent instance manages exactly one project; a project may span multiple code directories, PostgreSQL/MySQL/SQL Server databases, log directories, read-only HTTP endpoints, and "other" material sources (any local read-only files or folders: API/interface documents, data dictionaries, exported JSON/CSV, READMEs, etc.). There is no need to copy a sample file or hand-edit JSON first:

```powershell
python -m iro_agent.cli setup
```

Wizard order: **project & working directory → add one or more sources → models and optional Feishu credentials → validation, redacted summary, confirm & save**. In source management you can repeatedly add, remove, and view sources; each type can have multiple sources; skip types you do not need, but keep at least one source. Paths may contain Chinese characters, spaces, and quoted Windows paths. Enter `q` or press Ctrl+C to cancel; use `-` to clear an optional item; the existing configuration is not overwritten until completion.

Until the wizard is complete, `init`, `chat`, `investigate`, `gateway start`, and `eval` are all blocked and return a non-zero exit code. `eval` may invoke real sources and models and therefore also requires a completed configuration. Double-clicking `start_iro_agent.bat` on Windows checks first and automatically enters the wizard when not complete. An existing legacy `config.json` also requires running `setup` once; legacy source code, databases, logs, and credentials are imported for confirmation. The current user configuration is never rewritten automatically when the code is upgraded.

To add or remove sources later, simply run `setup` again. Directly modifying the project identity, source location, or purpose invalidates the completion marker and requires re-running the wizard; rotating passwords and environment-variable credential values does not change source identity. After a source changes, the old cognitive blueprint stops being used for queries — run `init` to rebuild. Help, configuration viewing, self-check, source inspection, and offline tests (`pytest`) are available before configuration is complete.

```powershell
# View sources (no live request is made)
python -m iro_agent.cli sources

# Explicitly check all sources: directory check / PostgreSQL SELECT 1 / HTTP GET
python -m iro_agent.cli sources --check

# Check the configuration-flow completion status
python -m iro_agent.cli setup --check

# When specifying a config file, put --config before the command; one process loads only the project of that file
python -m iro_agent.cli --config D:/site/IRO/config.json setup
```

The configuration file defaults to `config.json` in the **current directory**; it can also be set via `IRO_CONFIG_PATH`. It never auto-reads other installation directories, legacy projects, or `config.example.json`. The example file only documents the configuration structure and does not represent a completed configuration.

Database passwords can be selected as an environment-variable name or entered concealed and stored in the local configuration. HTTP authentication is configured via a request-header environment variable; the wizard saves only the variable name. For example, in PowerShell:

```powershell
$env:IRO_GLM_API_KEY = "your-model-key"
$env:ORDERS_DB_PASSWORD = "read-only-db-password"
$env:WES_AUTHORIZATION = "Bearer your-token"
python -m iro_agent.cli setup
```

For a database source, fill in the password environment variable `ORDERS_DB_PASSWORD`; for an HTTP source, add the request header `Authorization` referencing `WES_AUTHORIZATION`. These variables should be set in the same process environment that runs IRO; a temporary PowerShell variable is not automatically passed to another double-click-launched window. The wizard never writes environment-variable credential values into JSON. The model key can be skipped to use `init --static-only`; online Q&A and diagnosis still require valid model credentials.

At query time, the model receives the source ID, type, purpose, and location. Code, log, and database tools can select a source precisely by `source_id`; when omitted, they read all sources of that type, and both the returned results and failed items keep their source IDs. For example, you can ask: "search all code directories for 'dispatch'", "view the task status of the business DB and the scheduling DB separately", or "only query the task table in db-wes". PostgreSQL, MySQL, and SQL Server are supported; cross-database queries execute the SQL separately and do not support cross-database SQL JOIN. The version tool continues to use the first code source as the source-for-version, and keeps an optional WRelease delivery-version source. See [SQL Server setup notes](docs/261017_SQLServer_ReadOnly.md) for the ODBC driver prerequisite, default ports, schema, certificate handling, and per-dialect query syntax.

HTTP sources register **exact read-only GET endpoints**, including fixed query parameters; other URLs, dynamically appended paths, redirects, browser operations, or form logins are not accepted. Multiple endpoints can be registered one by one and read uniformly. Source checks can be explicitly skipped in the wizard; when a check fails, saving is allowed only if you explicitly choose to keep it. At runtime, if some sources are unavailable, existing results and observation gaps are returned together rather than being treated as zero records or "no anomaly"; a fault investigation can specify available sources for further verification.

"Other" sources accept any local absolute path to a folder or a single file (API/interface documents, data dictionaries, exported JSON/CSV, Markdown manuals, etc.). At query time the model uses the `other_read` tool: a single-file source is read directly; for a folder source it matches by file name/relative path (listing the candidates when several match), then reads the text content, optionally filtering lines by keyword. Binary and office files (PDF, Word, Excel, images, zip, etc.) are listed by location only and never decoded — export them as text (e.g. CSV/JSON/Markdown) if their content should be searchable. Like every other source, results keep their `source_id` and unavailable folders are reported as observation gaps.

### 3. Project knowledge bootstrap (Project Learning)

```bash
# Run deep project-knowledge bootstrap
python -m iro_agent.cli init

# Pure static mode (no external LLM API required)
python -m iro_agent.cli init --static-only
```

### 4. Interactive diagnosis & gateway service

```bash
# Interactive investigation session
python -m iro_agent.cli chat

# Start the enterprise collaboration gateway (e.g. Feishu long-connection gateway)
python -m iro_agent.cli gateway start
```

### 5. Run industrial evaluation sets

```bash
# Run the development evaluation set
python -m iro_agent.cli eval dev

# Run the regression quality-gate evaluation set
python -m iro_agent.cli eval regression

# Run an external private blind test set (provide the dataset path)
python -m iro_agent.cli eval external --dataset D:/path/to/blind_cases
```

Evaluation reports and trajectory replays are generated automatically at `<project_root>/.iro_agent/.eval_runs/<run_id>/report.md`.

### 6. Run the full automated test suite

```bash
pytest -q
```

The current local full test suite reports **338 tests passing** (plus 1 skip), covering the configuration wizard (including "other" material sources), multi-source reads, SQL Server read-only access, GLM chat finalization, source isolation, and regression validation. On-site data-source connectivity, online model services, and real SQL Server connections still need to be verified in the actual runtime environment.

### 7. Industrial PC version update & quick launch

- **Pull updates on the industrial PC (recommended command)**:
  The industrial PC is the production runner. To avoid history divergence or file conflicts interrupting `git pull`, it is recommended to force-align with the remote repository on every update (`config.json` and `.venv`, protected by `.gitignore`, are not overwritten):
  ```bash
  git fetch origin main && git reset --hard origin/main
  ```

- **Windows one-click interactive menu (`start_iro_agent.bat`)**:
  On Windows, double-click the root `start_iro_agent.bat`; the script integrates self-check, knowledge bootstrap, and daily investigation into an interactive menu to prevent on-site misoperation.

---

## Directory structure

```text
iro_agent/
├── runtime/                    # Unified runtime dispatch system
│   ├── dispatcher.py           # Enterprise-grade unified runtime message & fault dispatcher
│   └── models.py               # Routing enums and dispatch result models
├── investigation/              # Agentic Investigation Harness
│   ├── harness.py              # Per-round re-planning dynamic investigation engine
│   ├── llm_planner.py          # Structured LLM investigation planner (with self-correction)
│   ├── planner_validator.py    # Schema, read-only permission, and budget validator
│   ├── tool_registry.py        # Unified read-only tool registry and permission allow-list
│   ├── hypotheses.py           # Competing-hypothesis generation and lifecycle state machine
│   ├── evaluator.py            # Evidence fact extraction and observability-gap labeling
│   ├── state.py                # Dynamic investigation state machine and budget tracking
│   ├── stop_conditions.py      # State-driven deterministic stop decision
│   ├── trace.py                # Complete investigation trajectory and causal evidence provenance
│   └── physical_escalation.py  # Real physical escalation decision and guardrail
├── evaluation/                 # Evaluation Harness
│   ├── runner.py               # Production-identical benchmark runner (via RuntimeDispatcher)
│   ├── dataset.py              # Evaluation-set loading and format validation
│   ├── scoring.py              # 5-dimension weighted composite scoring
│   ├── reporter.py             # Detailed evaluation report generator
│   └── graders/                # Deterministic, evidence-grounding, safety, and path-quality graders
├── knowledge/                  # Project Learning Harness
│   ├── unknowns.py             # Unknown first-class objects and priority queue
│   ├── learning_state.py       # 10-dimension knowledge coverage state
│   ├── learning_loop.py        # Autonomous multi-round learning loop
│   ├── synthesizer.py          # Knowledge synthesizer (exposes failure stage, unified confidence)
│   ├── deep_reader.py          # Targeted module source-code deep read
│   └── store.py                # Blueprint persistence
├── memory/                     # Memory and anti-pollution
│   ├── incident_store.py       # Incident experience store (verification-status separation)
│   └── learning_store.py       # Operations rule store (injection anti-pollution provenance metadata)
├── readers/                    # Read-only data-source drivers (Log, Git, DB, WRelease)
├── security/                   # Read-only safety and redaction auditing
└── cli.py                      # Unified command-line entry point
```

---

## FAQ

**What is IRO_agent?**
IRO_agent (Industrial Read-Only Agent) is an evidence-driven diagnostic AI agent for industrial software systems. It learns a project's operational model, investigates incidents with iterative evidence gathering, and grades its own diagnosis quality.

**How is it different from a general chat assistant?**
It does not answer from fixed one-shot steps. It runs three closed-loop harnesses (Project Learning, Investigation, Evaluation), re-plans every round from fresh evidence, and requires every claim to be grounded in a specific log line, config key, or database record.

**Is it safe to run against a production system?**
Yes — the safety boundary is strict read-only. It performs no file writes, no Git commits, no business-database writes, and no arbitrary shell execution against the diagnosed system.

**What kinds of systems can it diagnose?**
Industrial and on-premise software such as scheduling/dispatcher systems (e.g. WES), PostgreSQL-backed business databases, service logs, and dynamic web pages (DevExpress Blazor Server, Vue, React, ASP.NET WebForms).

**Does it require internet access?**
No. It supports fully offline / air-gapped industrial PCs via a single-file `uv.exe` install path. A China mirror is also provided for downloading the Playwright Chromium kernel on weak/intranet networks.

**Which LLM does it use?**
The model is configurable (a GLM client is provided in the codebase, and model credentials can be set via environment variables). Offline static bootstrap works without an LLM API, but online Q&A and diagnosis require valid model credentials.

**How is diagnosis quality measured?**
Through the Evaluation Harness, with layered graders (deterministic, evidence-grounding, safety, path-quality) over DEV, REGRESSION, and private BLIND datasets.

**How do I get started?**
Run `python -m iro_agent.cli setup` to complete the one-time wizard, then `python -m iro_agent.cli init` to bootstrap knowledge, and `chat` / `gateway start` / `eval` for interactive diagnosis, collaboration gateway, and evaluation.

---

## License

This project is licensed under the MIT License.

Machine-readable metadata (JSON-LD / Schema.org) with the canonical name, description, keywords, and GitHub About/topics is available at [`docs/METADATA.json`](docs/METADATA.json).

[Runtime write boundary, C# text reading and MySQL setup (Chinese)](docs/261012_Readonly_CSharp_MySQL.md) · [SQL Server read-only access (Chinese)](docs/261017_SQLServer_ReadOnly.md)
