# CoDevx Agent Manifest — v4.0 (AgentScope Edition)

> This file is read by Cursor, GitHub Copilot, and other AI-native IDEs
> to understand the agents in this repository and how to interact with them.

## System Overview

**CoDevx** is an autonomous AI software development team that runs as a single FastAPI service (`agent_mesh.py`). Submit a task and all 8 agents collaborate dynamically — using AgentScope's **MsgHub** for real-time cross-agent communication and **self-correcting loops** for QA and Security — to produce production-ready code from architecture to deployed infrastructure.

**Trigger pipeline from your IDE:**
> _"Submit an order to CoDevx: [your feature description]"_

## The 8 Agents

### 1. Project Manager (`pm`)
- **Role:** Orchestrates the pipeline, decomposes tasks, writes delivery reports
- **AgentScope class:** `DialogAgent` → `ProjectManagerAgent`
- **Outputs:** Decomposed step list, final delivery summary `.md`
- **LLM temp:** 0.3 (structured, deterministic)
- **Tools:** `memory_read`, `memory_store`, `decompose_task`

### 2. Architect (`architect`)
- **Role:** Produces Architecture Decision Records (ADRs) with API contracts, data models, auth flows, and security design
- **AgentScope class:** `DialogAgent` → `ArchitectAgent`
- **Outputs:** `docs/architecture_<task>.md`, OpenAPI schema stubs, DB ERD
- **LLM temp:** 0.4
- **Artifacts:** ADR format: Context → Decision → Consequences, fitness functions

### 3. Frontend Developer (`frontend`)
- **Role:** Builds the user interface with React / Next.js
- **AgentScope class:** `DialogAgent` → `FrontendDevAgent`
- **Stack:** Next.js 14 App Router, TypeScript (strict), Tailwind CSS, shadcn/ui, React Query v5, Zod
- **Outputs:** `.tsx` components, Zod schemas, Vitest tests
- **LLM temp:** 0.6 (creative)
- **Standards:** Named exports only, WCAG 2.1 AA, no `any`

### 4. Backend Developer (`backend`)
- **Role:** Implements API routes, business logic, service layer
- **AgentScope class:** `DialogAgent` → `BackendDevAgent`
- **Stack:** FastAPI, Python 3.12, async SQLAlchemy 2.0, structlog, Pydantic v2
- **Outputs:** `.py` route files, service classes, Pydantic schemas
- **LLM temp:** 0.4
- **Standards:** Full type hints, parameterized SQL, no `print()`, async throughout

### 5. Database Engineer (`database`)
- **Role:** Designs schemas, writes migrations, configures caching
- **AgentScope class:** `DialogAgent` → `DatabaseEngineerAgent`
- **Stack:** PostgreSQL, Alembic, RLS policies, Redis
- **Outputs:** `alembic/versions/*.py`, `sql/schema.sql`, `sql/rls.sql`
- **LLM temp:** 0.25 (highly precise)
- **Standards:** Declarative Base, `BIGSERIAL` PKs, `updated_at` triggers, RLS enabled

### 6. QA Engineer (`qa`)
- **Role:** Writes and runs automated tests; self-corrects failures via tool loop
- **AgentScope class:** `ReActAgent` → `QAEngineerAgent` (with `run_pytest` tool)
- **Stack:** pytest, hypothesis, Vitest, httpx.AsyncClient
- **Outputs:** `tests/test_*.py`, `*.test.tsx`, coverage reports
- **LLM temp:** 0.3
- **Gate:** ≥85% branch coverage required to pass
- **Self-correcting loop:** pytest FAIL → ask Backend/Frontend to fix → retry (up to `MAX_RETRIES`)

### 7. Security Analyst (`security`)
- **Role:** Audits code for vulnerabilities; self-corrects findings via tool loop
- **AgentScope class:** `ReActAgent` → `SecurityAnalystAgent` (with `run_bandit` + `run_npm_audit` tools)
- **Framework:** OWASP Top 10, ASVS L2, CWE Top 25
- **Outputs:** `docs/security_review_<task>.md`, inline fix patches
- **LLM temp:** 0.2 (conservative)
- **Self-correcting loop:** HIGH finding → ask Backend Dev to patch → re-scan (up to `MAX_RETRIES`)

### 8. DevOps Engineer (`devops`)
- **Role:** Packages, deploys, and monitors the application
- **AgentScope class:** `ReActAgent` → `DevOpsEngineerAgent` (with `git_commit_push` tool)
- **Stack:** Docker (distroless base images), GitHub Actions, Kubernetes, Prometheus + Grafana
- **Outputs:** `Dockerfile`, `.github/workflows/*.yml`, `k8s/*.yaml`, `monitoring/`
- **LLM temp:** 0.35
- **Standards:** Non-root containers, resource limits, readiness probes, OTel tracing

---

## Pipeline Flow (v4.0 — AgentScope)

```
User Order
    ↓
[PM] Decompose → steps[]
    ↓
[Architect] ADR + API contracts + memory recall
    ↓
╔════════════════════════════════════════════════╗
║  MsgHub Collaboration (MSGHUB_ROUNDS rounds)  ║
║                                                ║
║  Architect broadcasts architecture design      ║
║       ↓                    ↓                  ║
║  [Frontend Dev]       [Backend Dev]            ║
║       ↕ "What is the /api/orders payload?"     ║
║       ↕ "It's {id, items[], total}"            ║
║       ↕  (back-and-forth N rounds)             ║
║  FE writes components  BE writes routes        ║
╚════════════════════════════════════════════════╝
    ↓
[DB Engineer] Schema + migrations
    ↓
[QA Engineer] Tests → run_pytest → self-correcting loop:
    ↓  FAIL → "Fix request → Backend Dev + Frontend Dev → retry"
    ↓  PASS ✅
[Security Analyst] SAST → run_bandit + run_npm_audit → self-correcting loop:
    ↓  HIGH → "Patch request → Backend Dev → re-scan"
    ↓  CLEAN ✅
[DevOps Engineer] Docker + CI/CD + K8s (git_commit_push via ServiceToolkit)
    ↓
[PM] Delivery report + memory store
    ↓
Git commit → feat/xxxx branch → GitHub PR → Discord/WhatsApp notification
```

---

## MsgHub Collaboration Topology (Phase 2)

```
Architecture Doc (broadcast)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    AgentScope MsgHub                     │
│                                                          │
│  ┌─────────────┐    Questions/Answers    ┌────────────┐ │
│  │ FrontendDev │◄───────────────────────►│ BackendDev │ │
│  │  (React/TS) │   "What is the shape    │ (FastAPI)  │ │
│  │             │    of /api/orders?"     │            │ │
│  └─────────────┘                         └────────────┘ │
│         │                                      │         │
│         └──────────── Architecture ────────────┘         │
│                      (shared context)                     │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   FE files written      BE files written
   (components, forms)   (routes, services)
```

---

## Self-Correcting QA Loop

```
[QA Engineer] writes test files
      ↓
[ServiceToolkit] run_pytest_service()
      ↓
   PASSED? ──→ YES ──→ continue pipeline ✅
      │
      NO
      ↓
[QA Agent] analyzes failure output
      ↓
[Backend Dev] receives fix request → patches code
[Frontend Dev] receives fix request → patches code
      ↓
[ServiceToolkit] run_pytest_service() — retry 1/MAX_RETRIES
      ↓
   PASSED? ──→ YES ──→ continue ✅
      │
      NO (up to MAX_RETRIES total)
      ↓
   Continue with warning in delivery report
```

---

## Self-Correcting Security Loop

```
[Security Analyst] reviews code (LLM)
      ↓
[ServiceToolkit] run_bandit_service() + run_npm_audit_service()
      ↓
   CLEAN? ──→ YES ──→ continue pipeline ✅
      │
      NO (HIGH/CRITICAL findings)
      ↓
[Security Agent] formulates patch request
      ↓
[Backend Dev] receives security fix request → patches code
      ↓
[ServiceToolkit] run_bandit_service() — retry 1/MAX_RETRIES
      ↓
   CLEAN? ──→ YES ──→ continue ✅
      │
      NO (up to MAX_RETRIES total)
      ↓
   Continue with security warning in delivery report
```

---

## ServiceToolkit Services

| Service | Agent | Wraps | Returns |
|---------|-------|-------|---------|
| `run_pytest_service` | QA Engineer | `run_pytest()` | `{passed, output, test_count}` |
| `run_bandit_service` | Security Analyst | `run_bandit()` | `{clean, output}` |
| `run_npm_audit_service` | Security Analyst | `run_npm_audit()` | `{clean, output}` |
| `git_commit_push_service` | DevOps Engineer | `git_commit_push()` | `{pr_url, branch, task_id}` |
| `write_file_service` | all agents | `write_workspace_file()` | `{path, task_id}` |
| `read_architecture_service` | all agents | `_read_project_architecture()` | `{architecture}` |

---

## Memory Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dual Memory System                    │
│                                                          │
│  ┌──────────────────────┐   ┌────────────────────────┐  │
│  │   AgentScope         │   │   SQLite               │  │
│  │   ListMemory         │   │   agent_memory table   │  │
│  │   (in-context)       │   │   (cross-session)      │  │
│  │                      │   │                        │  │
│  │  • Per-agent         │   │  • Persists restarts   │  │
│  │  • Ephemeral         │   │  • Full history        │  │
│  │  • Token-aware       │   │  • Keyword search      │  │
│  │  • Auto-managed      │   │  • MEMORY_CONTEXT_K    │  │
│  │    by AgentScope     │   │    entries injected    │  │
│  └──────────────────────┘   └────────────────────────┘  │
│           │                           │                  │
│           └─────── merged at run ─────┘                  │
│                    via recall_and_inject_memories()       │
└─────────────────────────────────────────────────────────┘
```

At the start of each pipeline run:
1. SQLite memories for each agent are loaded via `db_recall_memories(agent, MEMORY_CONTEXT_K)`
2. Loaded into the agent's `ListMemory` via `recall_and_inject_memories()`
3. New findings/patterns are stored back to SQLite via `db_store_memory()`

---

## MCP Tools (callable from IDE AI agents)

The CoDevx backend exposes an MCP server at `http://localhost:8000/mcp`.

| Tool Name | Parameters | Description |
|-----------|-----------|-------------|
| `codevx_submit_order` | `task: str` | Start the full pipeline with a task description |
| `codevx_get_state` | — | All agent statuses and active task details |
| `codevx_get_history` | — | Completed tasks with files, branches, PR URLs |
| `codevx_get_logs` | `limit?: int` | Recent pipeline activity logs |
| `codevx_get_agent` | `name: str` | Status of a specific agent by name |
| `codevx_get_agentscope_status` | — | **[NEW]** AgentScope config: model, memory backend, hub topology |

---

## How to Add a New Agent

1. Add the agent's system prompt to `AGENT_SYSTEM_PROMPTS` in `agent_mesh.py`
2. Create a new class in `agentscope_agents.py`:
   ```python
   class MyNewAgent(CoDevxAgentBase):
       AGENT_NAME = "My New Agent"
       DEFAULT_TEMPERATURE = 0.4
   ```
3. Add to `SYSTEM_STATE["agents"]` in `agent_mesh.py`
4. Add to `build_agents()` in `agentscope_agents.py`
5. Wire into `agentscope_pipeline.py` at the appropriate pipeline phase

---

## How to Change the LLM Model Per Agent

By default all agents use `codevx-primary` (driven by `LLM_MODEL` env var).

To assign a different model to a specific agent:
```python
# In agentscope_agents.py build_agents():
agents = {
    ...
    "Security Analyst": SecurityAnalystAgent(
        model_config_name="codevx-claude"  # Use Claude for security analysis
    ),
    ...
}
```

Available model configs are defined in `config/agentscope_model_config.yaml`
and built dynamically from env vars by `agentscope_init.py`.

---

## Starting the System

```bash
# Install deps (includes AgentScope)
pip install -r requirements.txt

# Configure
cp .env.example .env   # fill in OPENAI_API_KEY, DISCORD_TOKEN, etc.

# Run
python agent_mesh.py
# → FastAPI on http://localhost:8000
# → MCP server on http://localhost:8000/mcp
# → Dashboard on http://localhost:8000
# → AgentScope: ✅ Active (MsgHub + self-correcting loops)
```

## Key Files

| File | Purpose |
|------|---------|
| `agent_mesh.py` | Entire backend — FastAPI + 8-agent pipeline (single file by design) |
| `agentscope_init.py` | AgentScope initialization — multi-backend model config from env vars |
| `agentscope_agents.py` | 8 DialogAgent/ReActAgent wrappers with ListMemory |
| `agentscope_tools.py` | ServiceToolkit: pytest, bandit, npm-audit, git as LLM-callable services |
| `agentscope_pipeline.py` | Full pipeline with MsgHub Phase 2 + self-correcting loops |
| `config/agentscope_model_config.yaml` | Reference model config for multi-model deployments |
| `zeroclaw_squad.yaml` | Team config, pipeline phases, AgentScope topology |
| `.env.example` | Required environment variables |
| `command-center/` | React 19 PWA dashboard |
| `docs/architecture.md` | Full system architecture |
