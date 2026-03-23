# CoDevx — GitHub Copilot Workspace Instructions

You are working inside the **CoDevx** repository — an autonomous 8-agent AI software development team.

## What this system does

CoDevx runs a FastAPI backend (`agent_mesh.py`) that orchestrates 8 specialized AI agents through a full SDLC pipeline:

| Agent | Responsibility |
|-------|---------------|
| **Project Manager** | Decomposes tasks, writes delivery reports, stores memories |
| **Architect** | Produces Architecture Decision Records (ADRs) with API contracts, data models, security design |
| **Frontend Dev** | Next.js 14 App Router + TypeScript + Tailwind CSS + shadcn/ui |
| **Backend Dev** | FastAPI + Python 3.12 + async SQLAlchemy 2.0 + structlog |
| **Database Engineer** | PostgreSQL + Alembic migrations + RLS + Redis |
| **QA Engineer** | pytest + hypothesis + Vitest + ≥85% branch coverage gate |
| **Security Analyst** | OWASP Top 10 + ASVS L2 + CWE Top 25 + bandit + npm audit |
| **DevOps Engineer** | Docker (distroless) + GitHub Actions + K8s manifests + Prometheus |

## MCP Integration

The system exposes an **MCP (Model Context Protocol) server** at `http://localhost:8000/mcp`.

Available MCP tools you can call from Copilot Chat:
- `codevx_submit_order` — submit a development task to the full SDLC pipeline
- `codevx_get_state` — get current agent statuses and active task
- `codevx_get_history` — list completed tasks with files, branch, PR URL
- `codevx_get_logs` — tail recent activity logs
- `codevx_get_agent` — get status of a specific agent by name

**To trigger the pipeline from Copilot Chat:**
> "Submit an order to CoDevx: build a user authentication service with JWT and refresh tokens"

## Code Standards (enforce these when editing this repo)

- Python: PEP 8, full type hints, async/await throughout, `structlog` for logging, never `print()` in production
- SQL: parameterized queries only — never string formatting
- Frontend: named exports only, no `any`, Zod validation on all forms
- Tests: mock all external I/O, ≥85% branch coverage, always use `httpx.AsyncClient` for FastAPI tests
- Security: never hardcode secrets, always rate-limit auth endpoints, CORS must not allow `*` in production

## Key files

- `agent_mesh.py` — the entire backend (1700+ lines, single-file by design)
- `zeroclaw_squad.yaml` — team configuration, pipeline phases, storage settings
- `.env.example` — copy to `.env` with your credentials
- `command-center/` — React 19 PWA dashboard
- `docs/architecture.md` — full system architecture

## When asked to modify this codebase

1. Always read the relevant section of `agent_mesh.py` before editing
2. Preserve the section comment structure (`# ====... # N. SECTION NAME`)
3. Keep the single-file architecture — do not split `agent_mesh.py` unless explicitly asked
4. Run `python -m py_compile agent_mesh.py` to verify syntax before committing
