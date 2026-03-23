# CoDevx Agent Manifest

> This file is read by Cursor, GitHub Copilot, and other AI-native IDEs
> to understand the agents in this repository and how to interact with them.

## System Overview

**CoDevx** is an autonomous AI software development team that runs as a single FastAPI service (`agent_mesh.py`). Submit a task and all 8 agents collaborate sequentially to produce production-ready code — from architecture to deployed infrastructure.

**Trigger pipeline from your IDE:**
> _"Submit an order to CoDevx: [your feature description]"_

## The 8 Agents

### 1. Project Manager (`pm`)
- **Role:** Orchestrates the pipeline, decomposes tasks, writes delivery reports
- **Outputs:** Decomposed step list, final delivery summary `.md`
- **LLM temp:** 0.3 (structured, deterministic)
- **Tools:** `memory_read`, `memory_store`, `decompose_task`

### 2. Architect (`architect`)
- **Role:** Produces Architecture Decision Records (ADRs) with API contracts, data models, auth flows, and security design
- **Outputs:** `docs/architecture_<task>.md`, OpenAPI schema stubs, DB ERD
- **LLM temp:** 0.4
- **Artifacts:** ADR format: Context → Decision → Consequences, fitness functions

### 3. Frontend Developer (`frontend`)
- **Role:** Builds the user interface with React / Next.js
- **Stack:** Next.js 14 App Router, TypeScript (strict), Tailwind CSS, shadcn/ui, React Query v5, Zod
- **Outputs:** `.tsx` components, Zod schemas, Vitest tests
- **LLM temp:** 0.6 (creative)
- **Standards:** Named exports only, WCAG 2.1 AA, no `any`

### 4. Backend Developer (`backend`)
- **Role:** Implements API routes, business logic, service layer
- **Stack:** FastAPI, Python 3.12, async SQLAlchemy 2.0, structlog, Pydantic v2
- **Outputs:** `.py` route files, service classes, Pydantic schemas
- **LLM temp:** 0.4
- **Standards:** Full type hints, parameterized SQL, no `print()`, async throughout

### 5. Database Engineer (`database`)
- **Role:** Designs schemas, writes migrations, configures caching
- **Stack:** PostgreSQL, Alembic, RLS policies, Redis
- **Outputs:** `alembic/versions/*.py`, `sql/schema.sql`, `sql/rls.sql`
- **LLM temp:** 0.25 (highly precise)
- **Standards:** Declarative Base, `BIGSERIAL` PKs, `updated_at` triggers, RLS enabled

### 6. QA Engineer (`qa`)
- **Role:** Writes and runs automated tests against the generated code
- **Stack:** pytest, hypothesis, Vitest, httpx.AsyncClient
- **Outputs:** `tests/test_*.py`, `*.test.tsx`, coverage reports
- **LLM temp:** 0.3
- **Gate:** ≥85% branch coverage required to pass
- **Tools:** Runs `pytest` + `vitest` in subprocess, validates output

### 7. Security Analyst (`security`)
- **Role:** Audits code for vulnerabilities, enforces security standards
- **Framework:** OWASP Top 10, ASVS L2, CWE Top 25
- **Outputs:** `docs/security_review_<task>.md`, inline fix patches
- **LLM temp:** 0.2 (conservative)
- **Tools:** `bandit` (Python SAST), `npm audit` (JS deps), code review
- **Gate:** No critical/high findings allowed through

### 8. DevOps Engineer (`devops`)
- **Role:** Packages, deploys, and monitors the application
- **Stack:** Docker (distroless base images), GitHub Actions, Kubernetes, Prometheus + Grafana
- **Outputs:** `Dockerfile`, `.github/workflows/*.yml`, `k8s/*.yaml`, `monitoring/`
- **LLM temp:** 0.35
- **Standards:** Non-root containers, resource limits, readiness probes, OTel tracing

## Pipeline Flow

```
User Order
    ↓
[PM] Decompose → steps[]
    ↓
[Architect] ADR + API contracts
    ↓
[DB Engineer] Schema + migrations
    ↓
[Backend Dev] API routes + services
    ↓
[Frontend Dev] UI components + forms
    ↓
[QA Engineer] Tests → run pytest/vitest
    ↓
[Security Analyst] SAST + audit → patches
    ↓
[DevOps Engineer] Docker + CI/CD + K8s
    ↓
Git commit → branch → PR → Discord/WhatsApp notification
```

## MCP Tools (callable from IDE AI agents)

The CoDevx backend exposes an MCP server at `http://localhost:8000/mcp`.

| Tool Name | Parameters | Description |
|-----------|-----------|-------------|
| `codevx_submit_order` | `task: str` | Start the full pipeline with a task description |
| `codevx_get_state` | — | All agent statuses and active task details |
| `codevx_get_history` | — | Completed tasks with files, branches, PR URLs |
| `codevx_get_logs` | `limit?: int` | Recent pipeline activity logs |
| `codevx_get_agent` | `name: str` | Status of a specific agent by name |

## Starting the System

```bash
# Install deps
pip install -r requirements.txt

# Configure
cp .env.example .env   # fill in OPENAI_API_KEY, DISCORD_TOKEN, etc.

# Run
python agent_mesh.py
# → FastAPI on http://localhost:8000
# → MCP server on http://localhost:8000/mcp
# → Dashboard on http://localhost:8000
```

## Key Files

| File | Purpose |
|------|---------|
| `agent_mesh.py` | Entire backend — FastAPI + 8-agent pipeline (single file by design) |
| `zeroclaw_squad.yaml` | Team config, pipeline phases, ZeroClaw gateway |
| `.env.example` | Required environment variables |
| `command-center/` | React 19 PWA dashboard |
| `docs/architecture.md` | Full system architecture |
