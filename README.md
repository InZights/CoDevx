# CoDevx — Agent Mesh v4.0

> **A production-grade, 8-agent AI software development team** that takes a plain-English task description and delivers a working, tested, and committed codebase — complete with architecture docs, frontend, backend, database migrations, test suites, security scan, CI/CD configuration, and a GitHub PR.

---

## Table of Contents

1. [What is this?](#what-is-this)
2. [How it works](#how-it-works)
3. [Agent Squad](#agent-squad)
4. [Architecture](#architecture)
5. [Prerequisites](#prerequisites)
6. [Quick Start (local dev)](#quick-start-local-dev)
7. [Docker Deployment](#docker-deployment)
8. [Messaging Provider Setup](#messaging-provider-setup)
   - [Discord](#discord)
   - [WhatsApp via Twilio](#whatsapp-via-twilio)
   - [ZeroClaw (all channels)](#zeroclaw-all-channels-unified-gateway)
9. [LLM Configuration](#llm-configuration)
10. [Configuration Reference](#configuration-reference)
11. [The SDLC Pipeline](#the-sdlc-pipeline)
12. [Pipeline v4.0 — Production Features](#pipeline-v40--production-features)
13. [Command Center UI](#command-center-ui)
14. [Project Structure](#project-structure)
15. [Development Guide](#development-guide)

---

## What is this?

**CoDevx** is an autonomous software development infrastructure powered by eight specialized AI agents collaborating through a structured SDLC (Software Development Life Cycle) pipeline.

You give it an order: _"Build a multi-tenant SaaS billing system with Stripe integration"_ via Discord, WhatsApp, Telegram, or any other messaging platform. The system:

1. **Designs** the full architecture
2. **Breaks** the work into implementation phases
3. **Writes** production-grade frontend (React + TypeScript) and backend (FastAPI + Python) code **in parallel**
4. **Writes** database migrations with proper indexes, RLS policies, and soft deletes
5. **Writes** a full test suite and **actually runs it** (pytest + vitest)
6. **Runs a real security scan** (bandit + npm audit), applies fixes if needed, re-scans
7. **Generates CI/CD** (GitHub Actions + Dockerfile + docker-compose)
8. **Commits** to a feature branch and opens a **GitHub Pull Request**
9. **Delivers a delivery report** over your messaging channel
10. **Remembers** what it built, injecting relevant context into future tasks

All of this happens autonomously. You only approve the architecture plan before execution begins.

---

## How it works

```mermaid
flowchart TD
    User(["👤 You\n(Discord / WhatsApp / Telegram)"])
    ML["🌐 Messaging Layer\nZeroClaw / Discord Bot / Twilio WA"]
    AM["⚙️ agent_mesh.py\nFastAPI · SQLite · WebSocket"]

    User -->|"order: build a SaaS billing system"| ML
    ML -->|"webhook POST · HMAC-SHA256"| AM
    AM -->|"reply_url callback"| ML
    ML -->|"Delivery report"| User

    AM --> Arch

    subgraph Pipeline ["8-Agent SDLC Pipeline"]
        direction TB
        Arch["🟣 Architect\nADR · API contracts · phase decomposition"]

        subgraph Parallel ["Phase 1..N  (parallel)"]
            direction LR
            FE["🔵 Frontend Dev\nNext.js · TypeScript · Tailwind"]
            BE["🟢 Backend Dev\nFastAPI · Python 3.12 · SQLAlchemy"]
            DB["⚫ Database Engineer\nPostgreSQL · Alembic · Redis"]
        end

        QA["🟡 QA Engineer\npytest · Vitest · hypothesis\ncoverage gate ≥ 85%"]
        Sec["🔴 Security Analyst\nbandit · npm audit · OWASP ASVS\nauto-patch loop"]
        DevOps["🟠 DevOps Engineer\nDocker · GitHub Actions · K8s manifests"]
        Git["📦 Git commit + GitHub PR\nfeat/xxxx branch · auto-push"]
        PM["🔵 Project Manager\nDelivery report · memory store"]
    end

    Arch -->|"design doc"| Parallel
    Parallel --> QA
    QA -->|"retry on failure"| QA
    QA --> Sec
    Sec -->|"fix loop"| Sec
    Sec --> DevOps
    DevOps --> Git
    Git --> PM
    PM -->|"report"| AM
```

---

## Agent Squad

| Agent | Role | Key Standards |
|-------|------|---------------|
| **Architect** | System design, API contracts, data models, dependency selection | Architecture doc format, security design, scalability |
| **Frontend Dev** | React 19 / TypeScript / Tailwind UI | Named exports, Zod validation, React Query, aria-labels, no `any` |
| **Backend Dev** | FastAPI / Python 3.12 APIs | Parameterized SQL, JWT auth, rate limiting, structlog, no bare exceptions |
| **Database Engineer** | PostgreSQL / SQLite / Redis schemas | Idempotent DDL, soft deletes, RLS, indexes on all FKs |
| **QA Engineer** | pytest + Vitest test suites | ≥85% branch coverage, mocked externals, integration tests |
| **Security Analyst** | OWASP Top 10 review + tool scan | bandit + npm audit, SCAN: PASSED/FAILED verdict, auto-patches |
| **DevOps Engineer** | Docker + GitHub Actions CI/CD | Multi-stage builds, pinned versions, health checks, resource limits |
| **Project Manager** | Orchestration + delivery reports | Phase planning, memory storage, structured stakeholder report |

---

## Architecture

```
d:\Projects\AI-DEV-TEAM\
├── agent_mesh.py              FastAPI backend — the heart of the system
├── requirements.txt           Python 3.12 dependencies
├── Dockerfile                 Backend container (Python 3.12-slim)
├── docker-compose.yml         Multi-container: backend + React UI + nginx
├── .env.example               → copy to .env and fill in your credentials
├── zeroclaw_squad.yaml        Team configuration — agents, pipeline, storage
│
├── command-center/            React 19 + TypeScript + Tailwind PWA
│   ├── src/
│   │   ├── pages/             Dashboard, Agents, Logs, History, Settings
│   │   ├── components/        AgentGrid, TerminalLogs, TaskHistory, Header
│   │   ├── hooks/             useAgentState (WebSocket + auto-reconnect)
│   │   └── types/index.ts     Shared TypeScript types
│   ├── public/manifest.json   PWA metadata (installable on Android)
│   ├── public/sw.js           Service worker (offline support)
│   ├── nginx.conf             Reverse proxy → backend:8000
│   └── Dockerfile             Multi-stage: Node build → Nginx serve
│
└── docs/
    ├── zeroclaw/
    │   ├── config.toml.example    ZeroClaw gateway configuration template
    │   └── sop.yaml.example       ZeroClaw SOP webhook templates
    └── architecture.md            Extended architecture notes
```

**Data flow:**
- Backend runs on port **8000** (FastAPI + uvicorn)
- React dev server runs on port **5173** (Vite HMR, proxies `/api` + `/ws` → 8000)
- React production build served by Nginx on port **3000** (Docker)
- WebSocket `ws://host:8000/ws/state` pushes real-time agent status to all UI clients
- SQLite at `./agent_mesh.db` stores logs, task history, generated files, and agent memory

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | `python --version` |
| Node.js | 18+ | `node --version` |
| Git | 2.x | Must be on `PATH` for auto-commit |
| Docker + Docker Compose | 24+ | Optional — for containerized deployment |
| OpenAI API key | — | Optional — pipeline works in simulation mode without one |
| Discord Bot token | — | Optional — for Discord messaging |
| Twilio account | — | Optional — for WhatsApp messaging |
| ZeroClaw daemon | latest | Optional — for unified multi-channel messaging |

---

## Quick Start (local dev)

### 1. Clone and configure

```bash
git clone https://github.com/InZights/CoDevx.git
cd CoDevx
cp .env.example .env
# Edit .env — fill in at minimum OPENAI_API_KEY and one messaging provider
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
# For real tool execution (ENABLE_REAL_TOOLS=true):
pip install pytest pytest-cov pytest-asyncio bandit
```

### 3. Start the backend

```bash
python agent_mesh.py
# Server starts at http://localhost:8000
# WebSocket at ws://localhost:8000/ws/state
```

### 4. Start the React Command Center

```bash
cd command-center
npm install
npm run dev
# UI available at http://localhost:5173
```

### 5. Send your first order

Via Discord: `!order Build a REST API for a todo list app`  
Via WhatsApp: `order Build a REST API for a todo list app`  
Via REST API: `POST http://localhost:8000/api/order`  
```json
{ "task": "Build a REST API for a todo list app" }
```

The pipeline starts. Watch agents activate in the Command Center UI. Receive the delivery report with your PR link.

---

## Docker Deployment

### Full stack (recommended)

```bash
cp .env.example .env
# Edit .env with your credentials

docker compose up --build
```

Services:
- **Backend** → `http://localhost:8000`
- **Command Center** → `http://localhost:3000`

### Backend only

```bash
docker build -t codevx-backend .
docker run -p 8000:8000 --env-file .env codevx-backend
```

### Production considerations

```yaml
# docker-compose.yml — add these for production:
services:
  agent-mesh:
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512m
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## Messaging Provider Setup

Set `MESSAGING_PROVIDER` in `.env` to choose your channel:

| Value | Channels |
|-------|----------|
| `discord` | Discord server channels |
| `whatsapp` | WhatsApp via Twilio |
| `both` | Discord + WhatsApp simultaneously |
| `zeroclaw` | All channels via ZeroClaw gateway |

### Discord

1. Go to [discord.com/developers](https://discord.com/developers) → **New Application** → **Bot**
2. Enable **Message Content Intent** under Privileged Gateway Intents
3. Copy the **Bot Token** → set `DISCORD_TOKEN` in `.env`
4. Invite bot to server: OAuth2 → URL Generator → `bot` scope + `Send Messages`, `Read Messages` permissions
5. Create 4 channels in your server:
   - `#orders` — where you send `!order <task>`
   - `#plans` — where the Architect posts the plan (approve with ✅, reject with ❌)
   - `#activity-log` — live pipeline logs
   - `#reports` — delivery reports
6. Copy channel IDs (right-click channel → Copy ID — requires Developer Mode)
7. Set `CH_ORDERS`, `CH_PLANS`, `CH_LOGS`, `CH_REPORTS`, `MANAGER_DISCORD_ID` in `.env`

### WhatsApp via Twilio

1. Create a [Twilio](https://www.twilio.com) account
2. Enable the WhatsApp Sandbox (Messaging → Try it Out → Send a WhatsApp Message)
3. Set env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `MANAGER_WHATSAPP`
4. Expose your backend with ngrok: `ngrok http 8000`
5. In Twilio sandbox settings, set the webhook URL to: `https://<ngrok-id>.ngrok.io/webhook/whatsapp`
6. Send `!order <task>` to your Twilio WhatsApp number

### ZeroClaw (All Channels — Unified Gateway)

> ZeroClaw is a **Rust-native AI assistant daemon** (~8.8 MB binary, <5 MB RAM) that manages Discord, WhatsApp, Telegram, Slack, Signal, iMessage, Matrix, IRC, Email, Bluesky, and 20+ more channels from a single process. When `MESSAGING_PROVIDER=zeroclaw`, agent_mesh no longer runs discord.py or Twilio directly — ZeroClaw handles all channel I/O and calls the agent_mesh webhook.

**What ZeroClaw IS:**
- Single Rust binary that manages all messaging channels
- SOP (Standard Operating Procedure) webhook automation
- HMAC-SHA256 security between ZeroClaw and agent_mesh
- Pairing, sandboxing, approval gating, rate limiting
- Web dashboard at port 42617

**What ZeroClaw is NOT:**
- A Python library (cannot `pip install`) — install via the installer script
- A replacement for the SDLC pipeline (it's the channel/security layer)

**Setup:**

```bash
# 1. Install ZeroClaw
curl -fsSL https://zeroclawlabs.ai/install.sh | bash

# 2. Onboard (interactive — connects your channels)
zeroclaw onboard

# 3. Copy the configuration templates from docs/zeroclaw/
cp docs/zeroclaw/config.toml.example ~/.zeroclaw/config.toml
cp docs/zeroclaw/sop.yaml.example ~/.zeroclaw/workspace/sops/ai-devteam.yaml
# Edit both files with your credentials

# 4. Start the ZeroClaw daemon
zeroclaw daemon

# 5. Update .env
# MESSAGING_PROVIDER=zeroclaw
# ZEROCLAW_GATEWAY_URL=http://localhost:42617
# ZEROCLAW_WEBHOOK_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
```

**Security:** Every POST from ZeroClaw to `/webhook/zeroclaw` is HMAC-SHA256 signed. The same secret must be set in both `.env` (`ZEROCLAW_WEBHOOK_SECRET`) and `~/.zeroclaw/config.toml`.

---

## LLM Configuration

The pipeline uses the **OpenAI API** (or any compatible endpoint). Without an API key, all agents run in **simulation mode** — generating placeholder files so the full pipeline can be tested.

```env
OPENAI_API_KEY=sk-...           # Required for real code generation
OPENAI_MODEL=gpt-4o             # Default model
OPENAI_MAX_TOKENS=4000          # Tokens per agent call
```

### Compatible endpoints (set OPENAI_BASE_URL)

| Provider | OPENAI_BASE_URL |
|----------|----------------|
| OpenAI (default) | _(leave unset)_ |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<deployment>` |
| Ollama (local) | `http://localhost:11434/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Mistral | `https://api.mistral.ai/v1` |
| Any OpenAI-compatible | your endpoint |

---

## Configuration Reference

Copy `.env.example` to `.env` and configure:

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `MESSAGING_PROVIDER` | `discord` | `discord` \| `whatsapp` \| `both` \| `zeroclaw` |
| `OPENAI_API_KEY` | — | OpenAI API key (omit = simulation mode) |
| `OPENAI_MODEL` | `gpt-4o` | Model name |
| `OPENAI_BASE_URL` | — | Override for Azure / Ollama / Groq |
| `DB_PATH` | `./agent_mesh.db` | SQLite database path |
| `GIT_WORKSPACE` | `./workspace` | Directory agents write code to |

### Discord

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `MANAGER_DISCORD_ID` | Your Discord user ID (approve/reject gating) |
| `CH_ORDERS` | Channel ID for `!order` commands |
| `CH_PLANS` | Channel ID for plan approval |
| `CH_LOGS` | Channel ID for activity logs |
| `CH_REPORTS` | Channel ID for delivery reports |

### WhatsApp / Twilio

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_WHATSAPP_FROM` | Your Twilio WhatsApp number (`whatsapp:+1...`) |
| `MANAGER_WHATSAPP` | Your personal WhatsApp number (approvals) |

### GitHub

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | Personal access token (repo scope) - enables auto PR |
| `GITHUB_REPO` | `owner/repo` format |
| `GIT_USER_NAME` | Git commit author name |
| `GIT_USER_EMAIL` | Git commit author email |

### ZeroClaw

| Variable | Default | Description |
|----------|---------|-------------|
| `ZEROCLAW_GATEWAY_URL` | `http://localhost:42617` | ZeroClaw daemon URL |
| `ZEROCLAW_WEBHOOK_SECRET` | — | HMAC-SHA256 shared secret |

### Pipeline Tuning (v4.0)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MAX_TOKENS` | `4000` | Max tokens per agent LLM call |
| `MAX_RETRIES` | `2` | QA / Security gate retry attempts |
| `MAX_SUBTASKS` | `5` | Max implementation phases from task decomposition |
| `ENABLE_REAL_TOOLS` | `true` | Run pytest, bandit, npm audit during pipeline |
| `DOCKER_BUILD` | `false` | Docker build after DevOps generates Dockerfile |
| `MEMORY_CONTEXT_K` | `5` | Past agent memories injected into each Architect call |

---

## The SDLC Pipeline

Every task runs through 8 agents in a structured sequence:

```
1. Memory Recall
   └── Retrieve relevant past builds from agent_memory table (keyword search)

2. Architect (1x)
   └── Full system design: files, APIs, data models, security design, dependencies
   └── Context: past memories injected here

3. Task Decomposition
   └── Simple tasks → single phase
   └── Complex tasks → up to MAX_SUBTASKS ordered phases (LLM decides)

4. Per-Phase Loop [Frontend Dev + Backend Dev + Database Engineer]
   ├── Frontend Dev     (React 19 / TypeScript / Tailwind)   ─ parallel
   ├── Backend Dev      (FastAPI / Python 3.12)               ─ parallel
   └── Database Engineer (migrations, indexes, RLS)

   → Files written to GIT_WORKSPACE immediately after each agent

5. QA Gate (with retry loop, up to MAX_RETRIES)
   ├── QA Engineer writes test suites (pytest + Vitest)
   ├── ENABLE_REAL_TOOLS=true → runs: pytest --cov + npm test
   ├── Checks: coverage ≥ 80%, no test failures
   └── If fails → regenerate tests and re-run (up to MAX_RETRIES times)

6. Security Gate (with fix loop, up to MAX_RETRIES)
   ├── Security Analyst LLM review (OWASP Top 10)
   ├── ENABLE_REAL_TOOLS=true → runs: bandit + npm audit
   ├── If SCAN: FAILED → extract fix files, apply, re-scan
   └── If still failing after all retries → pipeline aborts with error

7. DevOps Engineer
   ├── Generates: Dockerfile, docker-compose.yml, .github/workflows/ci.yml, Makefile
   └── DOCKER_BUILD=true → actually runs `docker build`

8. Git Commit + GitHub PR
   └── Writes all files, commits to feat/<task-id>, pushes, opens PR

9. Project Manager
   ├── Compiles delivery report (phases, files, coverage, security, PR URL)
   └── Sends report back to you via your messaging channel

10. Memory Store
    └── Saves Architect design, Backend patterns, Security findings, PM summary
        to agent_memory table for future task context
```

---

## Pipeline v4.0 — Production Features

### Real Tool Execution

Unlike v3.0 which only asked the LLM to *imagine* it scanned code, v4.0 actually executes tools:

```
ENABLE_REAL_TOOLS=true (default)

QA:
  Python projects  → python -m pytest --tb=short -q --cov=. --cov-report=term-missing
  JS/TS projects   → npm test -- --run --reporter=verbose

Security:
  Python code      → python -m bandit -r . -ll -f txt --exit-zero
  npm packages     → npm audit --audit-level=high --json
```

Requires the tools to be installed:
```bash
pip install pytest pytest-cov pytest-asyncio bandit
# npm is already available if Node.js is installed
```

### Agent Memory (Cross-Task Learning)

After every completed task, 4 types of knowledge are stored:

```
task_id | agent            | category     | content
--------|------------------|--------------|--------
abc123  | Architect        | architecture | "Multi-tenant SaaS: use tenant_id FK..."
abc123  | Backend Dev      | patterns     | "JWT auth via python-jose, rate limiting..."
abc123  | Security Analyst | findings     | "MEDIUM: missing rate limit on /auth/login"
abc123  | Project Manager  | delivery     | "Built billing system in 3 phases..."
```

At the start of every new task, relevant memories (keyword-matched) are injected into the Architect's context. The system gets smarter with each task.

### Iterative QA Retry

```
Write tests → Run pytest/vitest → coverage < 80% or failures?
    → YES: Regenerate tests with failure context → retry (up to MAX_RETRIES)
    → NO:  Pass gate, continue
```

### Iterative Security Fix Loop

```
LLM review → bandit + npm audit → SCAN: FAILED?
    → YES: Extract fix files from LLM → write to workspace → re-scan (up to MAX_RETRIES)
    → NO:  Pass gate (or hard abort if all retries exhausted)
```

---

## Command Center UI

The React PWA provides a real-time dashboard for monitoring the pipeline.

**Access:**
- Local dev: `http://localhost:5173`
- Docker: `http://localhost:3000`
- Mobile: use your machine's LAN IP (Settings page → Backend URL field)

**Pages:**
| Page | Description |
|------|-------------|
| Dashboard | Active task, 8-agent status grid, live terminal logs |
| Agents | Per-agent detailed view with status badges |
| Logs | Full terminal log with text search |
| History | Completed tasks: files generated, PR URL, branch, test pass count |
| Settings | Configuration overview, messaging status, pipeline engine settings |

**PWA Installation (Android/iOS):**
1. Open Chrome/Safari → navigate to the Command Center URL
2. Chrome → ⋮ menu → **Add to Home Screen**
3. The app installs as "CmdCenter" with native app feel

**WebSocket auto-reconnect:** The UI reconnects automatically if the backend restarts or network drops. No manual refresh needed.

---

## Project Structure

```
AI-DEV-TEAM/
│
├── agent_mesh.py              # FastAPI backend (core — 1,518 lines)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Backend container image
├── docker-compose.yml         # Full-stack orchestration
├── .env.example               # Environment variable template → copy to .env
├── .gitignore                 # Git ignore rules
├── zeroclaw_squad.yaml        # Team/agent/pipeline configuration
│
├── command-center/            # React 19 + TypeScript + Tailwind PWA
│   ├── Dockerfile             # Multi-stage: Node build → Nginx
│   ├── nginx.conf             # Reverse proxy to backend
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── public/
│   │   ├── manifest.json      # PWA metadata
│   │   └── sw.js              # Service worker (offline)
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── components/
│       │   ├── AgentCard.tsx
│       │   ├── AgentGrid.tsx
│       │   ├── ActiveOrder.tsx
│       │   ├── Header.tsx
│       │   ├── MobileNav.tsx
│       │   ├── Sidebar.tsx
│       │   ├── TaskHistoryList.tsx
│       │   └── TerminalLogs.tsx
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── AgentsPage.tsx
│       │   ├── LogsPage.tsx
│       │   ├── HistoryPage.tsx
│       │   └── SettingsPage.tsx
│       ├── hooks/
│       │   └── useAgentState.ts   # WebSocket + state management
│       ├── types/
│       │   └── index.ts           # Shared TypeScript types
│       └── utils/
│           └── colors.ts
│
└── docs/
    ├── architecture.md            # Extended architecture notes
    └── zeroclaw/
        ├── config.toml.example    # ZeroClaw gateway config template
        └── sop.yaml.example       # ZeroClaw SOP webhook templates
```

---

## Development Guide

### Running the backend with hot-reload

```bash
uvicorn agent_mesh:app --reload --port 8000
```

### Running tests

```bash
# Backend
pip install pytest pytest-asyncio pytest-cov httpx
pytest --tb=short -q

# Frontend
cd command-center && npm test
```

### TypeScript type check

```bash
cd command-center && npx tsc --noEmit
```

### Building for production

```bash
# React UI
cd command-center && npm run build
# Output: command-center/dist/  (served by Nginx in Docker)
```

### Linting

```bash
# Python
pip install ruff
ruff check agent_mesh.py

# TypeScript
cd command-center && npm run lint
```

### Database inspection

```bash
sqlite3 agent_mesh.db
.tables          # logs, task_history, generated_files, agent_memory
.schema agent_memory
SELECT * FROM task_history ORDER BY id DESC LIMIT 5;
```

### Resetting agent memory

```bash
sqlite3 agent_mesh.db "DELETE FROM agent_memory;"
```

### Simulated pipeline (no API key needed)

Run without `OPENAI_API_KEY` — all agents produce placeholder files. The full pipeline runs end-to-end including git commit, so you can test the entire flow without spending LLM credits.

### Environment variables priority

1. `.env` file (loaded by python-dotenv on startup)
2. Actual shell environment variables (override `.env`)

---

## Security Notes

- **HMAC-SHA256** validates every ZeroClaw webhook POST — set `ZEROCLAW_WEBHOOK_SECRET` to a 64-char random hex string
- **Approval gating** — the Architect's plan must be explicitly approved before the pipeline runs
- **Parameterized SQL** — all database queries use aiosqlite parameterized statements (no injection risk)
- **No shell=True** — all subprocesses use `asyncio.create_subprocess_exec` (injection-safe)
- **Input validation** — all webhook request bodies are validated via Pydantic v2 models
- **GITHUB_TOKEN scope** — use `repo` scope only; never store in code, always in `.env`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `OPENAI_API_KEY not set` | Set key in `.env` — pipeline runs in simulation mode without it |
| `Discord bot offline` | Check `DISCORD_TOKEN`, ensure bot has Message Content Intent enabled |
| `git push failed` | Set `GITHUB_TOKEN` and `GITHUB_REPO` in `.env` for push/PR support |
| `bandit: command not found` | `pip install bandit` or set `ENABLE_REAL_TOOLS=false` |
| `pytest: no tests found` | QA gate still passes — no tests counted as "no runner detected" |
| `Memory recall empty` | Expected on first task — memories accumulate with each completed pipeline |
| `ZeroClaw webhook 401` | `ZEROCLAW_WEBHOOK_SECRET` mismatch between daemon config and `.env` |
| `Port 8000 already in use` | Kill existing process: `lsof -ti:8000 \| xargs kill` |

---

## License

MIT — see LICENSE for details.

---

*Built with FastAPI · React 19 · OpenAI · aiosqlite · Discord.py · Twilio · ZeroClaw*
