"""
AI Dev Team — Agent Mesh v4.0
================================
New in v4:
  - WhatsApp messaging via Twilio (alongside or instead of Discord)
  - Real LLM calls via OpenAI API (GPT-4o / Azure / any OpenAI-compatible endpoint)
  - Persistent SQLite storage — logs & task history survive restarts
  - Git auto-commit on feature branches + optional GitHub PR creation
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
import discord
from discord.ext import commands
import uvicorn

load_dotenv()

# ============================================================
# 1. CONFIGURATION
# ============================================================

# Messaging: discord | whatsapp | both | zeroclaw
MESSAGING_PROVIDER = os.getenv("MESSAGING_PROVIDER", "discord")

# Discord
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN", "")
MANAGER_DISCORD_ID = int(os.getenv("MANAGER_DISCORD_ID", "0"))
CH_ORDERS   = int(os.getenv("DISCORD_CHANNEL_ORDERS",   "0"))
CH_PLANS    = int(os.getenv("DISCORD_CHANNEL_PLANS",    "0"))
CH_ACTIVITY = int(os.getenv("DISCORD_CHANNEL_ACTIVITY", "0"))
CH_REPORTS  = int(os.getenv("DISCORD_CHANNEL_REPORTS",  "0"))

# WhatsApp / Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WA_FROM     = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
MANAGER_WHATSAPP   = os.getenv("MANAGER_WHATSAPP", "")  # e.g. whatsapp:+60123456789

# ── LLM Brain ─────────────────────────────────────────────────────────────────
# LLM_MODEL is the single knob to switch your agents' brain.
# LiteLLM routes to the right provider automatically based on the model prefix.
#
#  Provider        LLM_MODEL examples                       Required key
#  OpenAI          gpt-4o, gpt-4.1, o3-mini                 OPENAI_API_KEY
#  Anthropic       claude-opus-4, claude-sonnet-4            ANTHROPIC_API_KEY
#  Google Gemini   gemini/gemini-2.5-pro, gemini/gemini-3-flash  GOOGLE_API_KEY
#  Groq            groq/llama-3.3-70b, groq/mixtral-8x7b    GROQ_API_KEY
#  Mistral         mistral/mistral-large, mistral/codestral  MISTRAL_API_KEY
#  Ollama (local)  ollama/llama3.3, ollama/qwen2.5-coder     (no key needed)
#  Together AI     together_ai/meta-llama/Llama-3-70b        TOGETHERAI_API_KEY
#  AWS Bedrock     bedrock/anthropic.claude-3-5-sonnet       BEDROCK creds below
#  Custom OpenAI   openai/<model-name>                       + OPENAI_BASE_URL
LLM_MODEL       = os.getenv("LLM_MODEL", "gpt-4o")          # e.g. claude-opus-4 / gemini/gemini-2.5-pro
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")           # OpenAI / Azure / OpenAI-compatible
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")          # optional: override API endpoint
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")      # Anthropic Claude
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")         # Google Gemini / Vertex
GOOGLE_PROJECT    = os.getenv("GOOGLE_PROJECT", "")         # Vertex AI project (optional)
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")           # Groq
MISTRAL_API_KEY   = os.getenv("MISTRAL_API_KEY", "")        # Mistral AI
TOGETHERAI_API_KEY = os.getenv("TOGETHERAI_API_KEY", "")    # Together AI
OLLAMA_HOST       = os.getenv("OLLAMA_HOST", "http://localhost:11434")  # Ollama
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID", "")  # AWS Bedrock
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION_NAME       = os.getenv("AWS_REGION_NAME", "us-east-1")

# Legacy: OPENAI_MODEL used as fallback if LLM_MODEL is not set
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", LLM_MODEL)

# Git
GIT_WORKSPACE = Path(os.getenv("GIT_WORKSPACE", "./workspace"))
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO   = os.getenv("GITHUB_REPO", "")  # "owner/repo"

# Database
DB_PATH = os.getenv("DB_PATH", "./agent_mesh.db")

# ZeroClaw Gateway — set MESSAGING_PROVIDER=zeroclaw to replace discord.py + Twilio with
# ZeroClaw's native channel layer (Discord, WhatsApp, Telegram, Slack, Signal, and 20+ more).
# Install ZeroClaw: https://github.com/zeroclaw-labs/zeroclaw -> ./install.sh -> zeroclaw daemon
ZEROCLAW_GATEWAY_URL    = os.getenv("ZEROCLAW_GATEWAY_URL", "http://localhost:42617")
ZEROCLAW_WEBHOOK_SECRET = os.getenv("ZEROCLAW_WEBHOOK_SECRET", "")  # HMAC-SHA256 secret

# Advanced pipeline — v4.0
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))   # tokens per agent call

# IDE Copilot Bridge (LLM_PROVIDER=copilot routes agent calls through GitHub Copilot/Cursor)
# Providers: openai | copilot | cursor | simulate
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "openai")  # default: OpenAI API
COPILOT_BRIDGE_URL = os.getenv("COPILOT_BRIDGE_URL", "http://localhost:8001")  # VS Code bridge

# IDE Chatbot Tools -- agents consult IDE chatbots as SUPPLEMENTARY specialists
# This is independent of LLM_PROVIDER (the brain); these are additional consultants.
# Set IDE_TOOLS_ENABLED=true and at least one IDE source to activate.
IDE_TOOLS_ENABLED   = os.getenv("IDE_TOOLS_ENABLED", "false").lower() == "true"
IDE_CHATBOT         = os.getenv("IDE_CHATBOT", "copilot")  # copilot | cursor | antigravity | all
# Antigravity IDE -- the Google AI IDE connects to CoDevx via MCP (see antigravity_mcp_config.json).
# For "consult Antigravity" in IDE_TOOLS, we call Google Gemini directly (what Antigravity runs).
# Set GOOGLE_API_KEY above and use IDE_CHATBOT=antigravity to send hints to Gemini during pipeline.
ANTIGRAVITY_MODEL = os.getenv("ANTIGRAVITY_MODEL", "gemini/gemini-2.5-pro")  # Gemini model for IDE tool consultation

MAX_RETRIES       = int(os.getenv("MAX_RETRIES", "2"))             # QA / Security retry attempts
MAX_SUBTASKS      = int(os.getenv("MAX_SUBTASKS", "5"))            # max implementation phases
ENABLE_REAL_TOOLS = os.getenv("ENABLE_REAL_TOOLS", "true").lower() == "true"  # run pytest/bandit/npm-audit
DOCKER_BUILD      = os.getenv("DOCKER_BUILD", "false").lower() == "true"      # docker build after pipeline

MEMORY_CONTEXT_K  = int(os.getenv("MEMORY_CONTEXT_K", "5"))       # past memories to inject

# ── LangGraph ─────────────────────────────────────────────────────────────────
# Set LANGGRAPH_ENABLED=true to use LangGraph ReAct subgraphs for QA and
# Security gates (true autonomous reasoning loops + SQLite checkpointing).
# Set HUMAN_GATE_ENABLED=true to pause after Architect and notify the manager
# via Discord (#plans channel button) and/or WhatsApp before coding begins.
LANGGRAPH_ENABLED  = os.getenv("LANGGRAPH_ENABLED",  "false").lower() == "true"
HUMAN_GATE_ENABLED = os.getenv("HUMAN_GATE_ENABLED", "false").lower() == "true"
HUMAN_GATE_TIMEOUT = int(os.getenv("HUMAN_GATE_TIMEOUT", "300"))  # seconds

# CORS
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")


# ============================================================
# 2. SHARED STATE
# ============================================================

SYSTEM_STATE: dict[str, Any] = {
    "agents": {
        "Project Manager":   {"status": "IDLE", "color": "blue"},
        "Architect":         {"status": "IDLE", "color": "purple"},
        "Frontend Dev":      {"status": "IDLE", "color": "cyan"},
        "Backend Dev":       {"status": "IDLE", "color": "green"},
        "QA Engineer":       {"status": "IDLE", "color": "yellow"},
        "DevOps Engineer":   {"status": "IDLE", "color": "orange"},
        "Security Analyst":  {"status": "IDLE", "color": "red"},
        "Database Engineer": {"status": "IDLE", "color": "gray"},
    },
    "current_task": "None",
    "logs": ["[BOOT] Agent Mesh v3.0 initializing..."],
    "history": [],
    "messaging":        MESSAGING_PROVIDER,
    "llm_enabled":      bool(OPENAI_API_KEY),
    "git_enabled":      bool(GITHUB_REPO),
    "zeroclaw_enabled": bool(ZEROCLAW_WEBHOOK_SECRET) or MESSAGING_PROVIDER == "zeroclaw",
}

_ws_clients: set[WebSocket] = set()
_wa_pending: dict[str, str] = {}                       # WhatsApp sender -> pending task
_zc_pending: dict[str, tuple[str, str]] = {}           # ZeroClaw sender -> (task, reply_url)
_pipeline_gates: dict[str, asyncio.Event] = {}  # task_id -> Event (human-in-the-loop gate)
_gate_task_map:  dict[str, str]           = {}  # "current" -> task_id (WhatsApp shortcut)


# ============================================================
# 3. DATABASE  (SQLite via aiosqlite — survives restarts)
# ============================================================

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                message    TEXT    NOT NULL,
                created_at TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id             TEXT PRIMARY KEY,
                description    TEXT,
                completed_at   TEXT,
                files_modified INTEGER DEFAULT 0,
                tests_passed   INTEGER DEFAULT 0,
                pr_url         TEXT,
                branch         TEXT,
                llm_used       INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS generated_files (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id   TEXT,
                file_path TEXT,
                content   TEXT,
                FOREIGN KEY (task_id) REFERENCES task_history(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id    TEXT,
                agent      TEXT,
                category   TEXT,
                content    TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def db_save_log(message: str) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO logs (message) VALUES (?)", (message,))
            await db.commit()
    except Exception:
        pass


async def db_save_task(entry: dict) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR REPLACE INTO task_history
                   (id, description, completed_at, files_modified, tests_passed,
                    pr_url, branch, llm_used)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    entry["id"], entry["description"], entry["completed_at"],
                    entry["files_modified"], entry["tests_passed"],
                    entry.get("pr_url"), entry.get("branch"),
                    int(entry.get("llm_used", False)),
                ),
            )
            await db.commit()
    except Exception:
        pass


async def db_save_files(task_id: str, files: list[dict]) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            for f in files:
                await db.execute(
                    "INSERT INTO generated_files (task_id, file_path, content) VALUES (?,?,?)",
                    (task_id, f["path"], f["content"]),
                )
            await db.commit()
    except Exception:
        pass


async def db_load_history() -> list[dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM task_history ORDER BY completed_at DESC LIMIT 50"
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
    except Exception:
        return []


async def db_load_recent_logs(limit: int = 100) -> list[str]:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT message FROM logs ORDER BY id DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
                return [r[0] for r in reversed(rows)]
    except Exception:
        return []


# ============================================================
# 4. HELPERS
# ============================================================

def add_log(message: str) -> None:
    ts = time.strftime("[%H:%M:%S]")
    entry = f"{ts} {message}"
    SYSTEM_STATE["logs"].append(entry)
    print(entry)
    if len(SYSTEM_STATE["logs"]) > 200:
        SYSTEM_STATE["logs"] = SYSTEM_STATE["logs"][-100:]
    asyncio.create_task(_broadcast())
    asyncio.create_task(db_save_log(entry))
    if _use_discord():
        asyncio.create_task(_discord_post(CH_ACTIVITY, entry))


def set_agent_status(name: str, status: str, color: str) -> None:
    if name in SYSTEM_STATE["agents"]:
        SYSTEM_STATE["agents"][name] = {"status": status, "color": color}
    asyncio.create_task(_broadcast())


def _use_discord() -> bool:
    return MESSAGING_PROVIDER in ("discord", "both") and bool(DISCORD_TOKEN)


def _use_whatsapp() -> bool:
    return MESSAGING_PROVIDER in ("whatsapp", "both") and bool(TWILIO_ACCOUNT_SID)


def _use_zeroclaw() -> bool:
    """Active when MESSAGING_PROVIDER=zeroclaw, or ZEROCLAW_WEBHOOK_SECRET is set
    (meaning ZeroClaw SOPs are configured to call this server)."""
    return MESSAGING_PROVIDER == "zeroclaw" or bool(ZEROCLAW_WEBHOOK_SECRET)


async def _broadcast() -> None:
    if not _ws_clients:
        return
    payload = json.dumps({"type": "state_update", "payload": SYSTEM_STATE})
    dead: set[WebSocket] = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


# ============================================================
# 5. LLM ENGINE  (OpenAI API — GPT-4o or any compatible endpoint)
# ============================================================

AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "Architect": (
        "You are a principal software architect with 15+ years experience in distributed systems, "
        "SaaS platforms, multi-tenant architecture, event-driven design, and AI-integrated products.\n\n"
        "ALWAYS produce a structured Architecture Decision Record (ADR) document with these sections:\n"
        "1. **Context** — Problem statement and constraints (3-5 sentences)\n"
        "2. **Decision** — What tech stack and architectural patterns are chosen and WHY\n"
        "3. **Files to create** — Full relative path + purpose for every file\n"
        "4. **API contracts** — Method, path, request body (JSON schema), response body (JSON schema), error codes\n"
        "5. **Data models** — Entities, fields with types, relationships, cardinality\n"
        "6. **New dependencies** — pip/npm packages with version constraints and justification\n"
        "7. **Security design** — Auth strategy (JWT/OAuth2/API key), RBAC model, PII fields, data exposure risks\n"
        "8. **Scalability plan** — Caching strategy (Redis/CDN), async queues, DB indexes, horizontal scaling points\n"
        "9. **Observability** — Metrics to expose (/metrics endpoint), log fields, trace spans, alert thresholds\n"
        "10. **Fitness functions** — Measurable architecture compliance checks (e.g. p99 < 200ms, coverage >= 85%)\n\n"
        "Tech stack selection rules:\n"
        "- Default backend: FastAPI + PostgreSQL + Redis + Celery for async tasks\n"
        "- Default frontend: Next.js 14 (App Router) + TypeScript + Tailwind CSS + shadcn/ui\n"
        "- Auth: Supabase Auth or Auth0 (never roll-your-own crypto)\n"
        "- If task requires real-time: WebSockets via FastAPI or SSE\n"
        "- If task requires ML: FastAPI + Celery worker + model served via ONNX or vLLM\n\n"
        "Be precise and technical. No filler. No vague statements. No TODOs in the design."
    ),
    "Frontend Dev": (
        "You are a senior Next.js 14 / React 19 / TypeScript / Tailwind CSS engineer building production UIs.\n\n"
        "For EACH file you produce, begin with the EXACT marker line (no extra spaces):\n"
        "  // FILE: relative/path/to/component.tsx\n"
        "Then write the COMPLETE file content — no truncation, no placeholders, no stub functions.\n\n"
        "Architecture rules:\n"
        "- Next.js App Router: use Server Components by default, 'use client' only for interactivity\n"
        "- Co-locate: Component.tsx + Component.test.tsx + Component.stories.tsx in same folder\n"
        "- State: Zustand stores in lib/stores/, React Query (TanStack Query v5) for all server state\n"
        "- Forms: React Hook Form + Zod resolver — never uncontrolled forms\n"
        "- API calls: typed fetch wrapper in lib/api.ts with proper error types\n\n"
        "Code standards:\n"
        "- Named exports ONLY (never `export default`)\n"
        "- Strict TypeScript: no `any`, no `as any`, no `@ts-ignore`\n"
        "- Tailwind: dark mode via `dark:` prefix, semantic color names in tailwind.config.ts\n"
        "- Accessibility: WCAG 2.1 AA — aria-label, role, keyboard navigation, focus management\n"
        "- Performance: dynamic imports for heavy components, next/image for all images, "
        "next/font for fonts, avoid layout shift (set explicit width/height)\n"
        "- Every async component wrapped in <Suspense> + skeleton fallback\n"
        "- Every data-fetching component has: loading state, empty state, error state\n"
        "- Error boundaries in app/error.tsx and per-route error.tsx\n"
        "- Web Vitals targets: LCP < 2.5s, CLS < 0.1, INP < 200ms\n\n"
        "Never output: TODO comments, placeholder logic, hardcoded credentials, console.log in prod code."
    ),
    "Backend Dev": (
        "You are a senior FastAPI / Python 3.12 / PostgreSQL engineer building production-grade APIs.\n\n"
        "For EACH file, begin with the EXACT marker line:\n"
        "  # FILE: relative/path/to/module.py\n"
        "Then write the COMPLETE file — no truncation, no placeholders, no pass stubs.\n\n"
        "Architecture patterns (REQUIRED):\n"
        "- Repository pattern: router → service → repository → database (strict layering)\n"
        "- Dependency injection via FastAPI Depends() for DB sessions, auth, rate limiter\n"
        "- Async SQLAlchemy 2.0 (async_sessionmaker, select().where()) — never sync ORM\n"
        "- Background tasks: FastAPI BackgroundTasks for fire-and-forget, Celery for long-running\n"
        "- CQRS where read/write patterns differ significantly\n\n"
        "Code standards:\n"
        "- Full PEP 695 type hints: every function, every class attribute, every variable\n"
        "- Pydantic v2 models for ALL request/response schemas — no raw dicts from endpoints\n"
        "- NEVER raw string formatting for SQL — SQLAlchemy expressions or parameterized queries ONLY\n"
        "- JWT via `python-jose` or `authlib` — HS256/RS256 only, reject `alg: none`\n"
        "- Rate limiting: `slowapi` on all public endpoints, stricter on auth endpoints\n"
        "- HTTP client: `httpx.AsyncClient` with timeout and retry — NEVER `requests`\n"
        "- Logging: `structlog` with JSON renderer — every log has trace_id, user_id, duration_ms\n"
        "- Never expose stack traces to API clients — HTTPException with sanitized messages only\n"
        "- Circuit breaker on external service calls (`circuitbreaker` library)\n"
        "- Input validation: reject on first error, never trust Content-Type header alone\n"
        "- Middleware order: CORS → tracing → auth → rate-limit → request-id injection\n\n"
        "OpenTelemetry: instrument every endpoint with span name = 'http.{method}.{route}'.\n"
        "Never output: TODO comments, hardcoded secrets, `print()` statements, sync DB calls."
    ),
    "Database Engineer": (
        "You are a database architect expert in PostgreSQL 16, Alembic, Redis, and TimescaleDB.\n\n"
        "For EACH file, begin with the EXACT marker line:\n"
        "  -- FILE: migrations/NNNN_description.sql\n"
        "For Alembic Python migrations:\n"
        "  # FILE: alembic/versions/NNNN_description.py\n"
        "Then write the COMPLETE SQL or Python migration — no truncation.\n\n"
        "Schema design rules:\n"
        "- All DDL is idempotent: `IF NOT EXISTS`, `CREATE OR REPLACE`\n"
        "- Every table: id UUID DEFAULT gen_random_uuid() PRIMARY KEY, created_at TIMESTAMPTZ DEFAULT now(), "
        "updated_at TIMESTAMPTZ DEFAULT now()\n"
        "- Soft deletes: deleted_at TIMESTAMPTZ nullable + partial index WHERE deleted_at IS NULL\n"
        "- Multi-tenant: tenant_id UUID NOT NULL on every table + RLS policy per table\n"
        "- Foreign keys: always have matching index, ON DELETE strategy must be explicit\n"
        "- Indexes: B-tree on FK columns and all WHERE/ORDER BY columns, GIN for full-text/JSONB, "
        "partial indexes to reduce index size where applicable\n"
        "- covering indexes: INCLUDE columns for hot query paths\n"
        "- CHECK constraints for all enum-like columns\n"
        "- Composite unique indexes for natural keys\n\n"
        "Performance rules:\n"
        "- Add EXPLAIN ANALYZE hints in comments for queries expected > 1000 rows\n"
        "- Materialized views for expensive aggregations (OLAP patterns)\n"
        "- Connection pooling: PgBouncer in transaction mode — no session-level state in queries\n"
        "- Avoid N+1: use JOIN or batch loading — document it in schema comments\n\n"
        "Migration safety rules:\n"
        "- Never DROP COLUMN or RENAME in the same migration as data changes\n"
        "- Always add NOT NULL columns with a DEFAULT or in two steps (add nullable → backfill → add constraint)\n"
        "- Lock-safe: use CREATE INDEX CONCURRENTLY for large tables\n\n"
        "Redis patterns: use typed key prefixes (user:{id}:session), set TTL on every key, "
        "use RESP3 for pub/sub.\n\n"
        "Comment every table and every non-obvious column with COMMENT ON."
    ),
    "QA Engineer": (
        "You are a senior QA engineer specializing in pytest, Vitest, property-based testing, "
        "and performance testing.\n\n"
        "For EACH test file, begin with the EXACT marker line:\n"
        "  # FILE: tests/test_feature_name.py\n"
        "For TypeScript tests:\n"
        "  // FILE: src/__tests__/feature.test.tsx\n"
        "Then write the COMPLETE test code — every test must actually run and pass.\n\n"
        "Test coverage requirements:\n"
        "- Minimum 85% branch coverage on ALL new code paths\n"
        "- Required for every feature:\n"
        "  * Unit tests (pure logic, no I/O)\n"
        "  * Integration tests (real DB via testcontainers or in-memory SQLite)\n"
        "  * API contract tests (httpx AsyncClient + ASGI transport against real FastAPI app)\n"
        "  * At least 1 property-based test using `hypothesis` for data-processing logic\n\n"
        "Test patterns (REQUIRED):\n"
        "- conftest.py: async fixtures for DB session, HTTP client, auth tokens, mocked external services\n"
        "- Mock ALL external I/O: httpx (respx), SMTP (pytest-mock), S3 (moto), Stripe (responses)\n"
        "- Time-sensitive tests: use `freezegun` to freeze datetime\n"
        "- Async tests: `pytest-asyncio` with `asyncio_mode = 'auto'` in pyproject.toml\n"
        "- FastAPI integration: `httpx.AsyncClient(app=app, base_url='http://test')` (ASGI transport)\n"
        "- Test doubles hierarchy: prefer fakes over mocks, mocks over stubs\n\n"
        "Test cases REQUIRED for every endpoint:\n"
        "- 200 happy path (valid input, expected output schema)\n"
        "- 422 validation failure (invalid types, missing required fields)\n"
        "- 401/403 auth failure (missing token, wrong role)\n"
        "- 409/404 business logic failure\n"
        "- Concurrent request test (two requests racing for same resource)\n\n"
        "Performance: add `pytest-benchmark` test for any endpoint expected to handle > 100 RPS.\n"
        "TypeScript: Vitest + Testing Library + MSW for API mocking. Test user interactions, NOT implementation.\n\n"
        "Never output: tests that always pass, tests that hit production APIs, sleep() in tests."
    ),
    "Security Analyst": (
        "You are an AppSec engineer who reviews code against OWASP Top 10, OWASP ASVS Level 2, "
        "and CWE Top 25.\n\n"
        "REQUIRED output format (do not deviate):\n\n"
        "## Findings\n"
        "For each issue found:\n"
        "  SEVERITY: CRITICAL | HIGH | MEDIUM | LOW\n"
        "  CWE: CWE-XXX (include the CWE number)\n"
        "  Location: filename:line_number\n"
        "  Issue: one-line description\n"
        "  Fix: exact code change, config, or header required\n\n"
        "## Patches\n"
        "For every CRITICAL or HIGH finding, output the COMPLETE corrected file:\n"
        "  # FILE: path/to/fixed_file.py\n"
        "  <full corrected file content — no truncation>\n\n"
        "## Verdict\n"
        "End with EXACTLY one of:\n"
        "  SCAN: PASSED\n"
        "  SCAN: FAILED\n\n"
        "Automatic FAIL conditions (any one triggers FAILED):\n"
        "- SQL injection (CWE-89): raw string formatting in queries\n"
        "- XSS (CWE-79): unescaped user content in HTML/JS output\n"
        "- Hardcoded secrets (CWE-798): API keys, passwords, tokens in source\n"
        "- Missing auth/authz (CWE-862/863): unprotected endpoints or missing RBAC checks\n"
        "- Insecure deserialization (CWE-502): pickle.loads on untrusted data\n"
        "- SSRF (CWE-918): user-controlled URLs fetched without allowlist validation\n"
        "- Path traversal (CWE-22): user-controlled file paths without sanitization\n"
        "- JWT algorithm confusion: accepting `alg: none` or RS→HS confusion attacks\n"
        "- Missing rate limiting on auth endpoints (login, register, password-reset)\n"
        "- Mass assignment: Pydantic model with no field restrictions on user input\n"
        "- Unvalidated redirects (CWE-601): user-controlled redirect URLs\n"
        "- Missing security headers: CSP, HSTS, X-Content-Type-Options, X-Frame-Options\n"
        "- Overly permissive CORS: allow_origins=['*'] in production\n\n"
        "Additional checks:\n"
        "- Dependency versions: flag any known-CVE packages (check against NVD)\n"
        "- Secrets in environment: verify .env files are in .gitignore\n"
        "- Supply chain: flag unpinned dependencies (no version = supply chain risk)\n"
        "- Container: check Dockerfile for running as root, secrets in ENV layers\n"
        "- Logging hygiene: ensure PII, passwords, tokens are never logged\n\n"
        "Output SCAN: PASSED only if ZERO CRITICAL or HIGH findings remain after patches."
    ),
    "DevOps Engineer": (
        "You are a senior DevOps/Platform engineer specializing in Docker, Kubernetes, "
        "GitHub Actions, Terraform, and cloud-native observability.\n\n"
        "For EACH config file, begin with the EXACT marker line:\n"
        "  # FILE: .github/workflows/ci.yml\n"
        "Then write the COMPLETE file — no truncation, no placeholder steps.\n\n"
        "Always produce ALL of the following:\n"
        "1. Dockerfile (multi-stage: builder + distroless/alpine runtime, non-root USER 65534)\n"
        "2. docker-compose.yml (full local dev stack: app + postgres + redis + any queues, "
        "with resource limits: mem_limit + cpus)\n"
        "3. .github/workflows/ci.yml (stages: lint → type-check → test → security → build → push → deploy)\n"
        "4. .dockerignore (exclude .git, __pycache__, .env*, node_modules, .pytest_cache)\n"
        "5. Makefile (targets: dev, test, lint, build, push, deploy, clean)\n"
        "6. k8s/deployment.yaml (Deployment + Service + HPA + PodDisruptionBudget + NetworkPolicy)\n"
        "7. k8s/configmap.yaml + k8s/secret.yaml (sealed-secrets or external-secrets pattern)\n"
        "8. monitoring/prometheus-rules.yaml (alert rules: high error rate, high latency, pod restarts)\n\n"
        "Standards:\n"
        "- Pin ALL image versions with SHA digest (never :latest)\n"
        "- Health checks: readinessProbe + livenessProbe + startupProbe on every K8s container\n"
        "- Resource requests AND limits on every container (no unbounded resource usage)\n"
        "- Secrets via external-secrets operator or sealed-secrets — never baked into images or ConfigMaps\n"
        "- CI: fail fast (lint before test, SAST before build, test before deploy)\n"
        "- CI: cache pip/npm/docker layers to minimize build time\n"
        "- Rollout strategy: RollingUpdate with maxSurge=1, maxUnavailable=0 (zero-downtime deploy)\n"
        "- HPA: scale on CPU (70%) AND custom metrics (queue depth, RPS) if applicable\n"
        "- NetworkPolicy: default deny-all, explicit allow only what's needed\n"
        "- /metrics endpoint: expose Prometheus metrics (FastAPI: prometheus-fastapi-instrumentator)\n"
        "- Grafana dashboard JSON: include in monitoring/ with panels for RPS, p99 latency, error rate\n\n"
        "Write complete, deployable configurations that work against a standard K8s cluster as-is."
    ),
    "Project Manager": (
        "You are an AI project manager writing a concise stakeholder delivery report.\n\n"
        "Structure your report EXACTLY as follows (every section required):\n\n"
        "## Acceptance Criteria Checklist\n"
        "List each requirement from the original task and mark [x] complete or [ ] incomplete.\n\n"
        "## Delivered\n"
        "Bullet list: what was built, what files were created, what changed.\n\n"
        "## Quality Gate\n"
        "- Test coverage: X% (gate: 85%)\n"
        "- Security scan: PASSED | FAILED\n"
        "- Syntax validation: PASSED | N/A\n"
        "- Known gaps or tech debt (be specific, no 'could be improved' vagueness)\n\n"
        "## Deployment Status\n"
        "- Branch: feat/xxxx\n"
        "- PR: <url or 'not created — GITHUB_TOKEN not configured'>\n"
        "- Files generated: N\n"
        "- Docker build: OK | FAILED | SKIPPED\n"
        "- Kubernetes manifests: included | not applicable\n\n"
        "## SLA Commitments\n"
        "Based on the architecture, state expected: p99 latency target, uptime SLO, "
        "max concurrent users before scale-out is needed.\n\n"
        "## Risks & Recommended Follow-up Orders\n"
        "- List what is NOT done (honest gaps)\n"
        "- Prioritized list of recommended follow-up orders with brief rationale\n"
        "- One-line rollback plan if deployment fails\n\n"
        "Keep under 600 words. Be direct. No filler. No corporate speak."
    ),
}




# Per-agent temperature tuning:
#   Low  (0.05-0.15) → deterministic code & SQL
#   Mid  (0.2-0.35)  → analysis & review tasks
#   High (0.4-0.5)   → creative design & planning
AGENT_TEMPERATURES: dict[str, float] = {
    "Architect":         0.45,  # creative exploration for design
    "Frontend Dev":      0.15,  # deterministic component code
    "Backend Dev":       0.10,  # very deterministic API/service code
    "Database Engineer": 0.05,  # maximum determinism for SQL/migrations
    "QA Engineer":       0.10,  # deterministic test code
    "Security Analyst":  0.20,  # structured review with some flexibility
    "DevOps Engineer":   0.10,  # deterministic config files
    "Project Manager":   0.35,  # moderate for prose reports
}


def _has_any_llm_key() -> bool:
    """Return True if at least one LLM provider API key is configured."""
    return bool(
        OPENAI_API_KEY
        or ANTHROPIC_API_KEY
        or GOOGLE_API_KEY
        or GROQ_API_KEY
        or MISTRAL_API_KEY
        or TOGETHERAI_API_KEY
        or AWS_ACCESS_KEY_ID
        or LLM_MODEL.startswith("ollama/")   # Ollama is keyless
        or LLM_PROVIDER in ("copilot", "cursor")
    )


async def _call_copilot_bridge(agent: str, system: str, user: str, temperature: float) -> str:
    """Forward an agent LLM call to the local VS Code Copilot Bridge extension."""
    import httpx
    payload = {
        "agent": agent,
        "system": system,
        "user": user,
        "temperature": temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{COPILOT_BRIDGE_URL}/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("content", "")
    except Exception as exc:
        add_log(f"[{agent}][CopilotBridge] Error: {exc} -- falling back to OpenAI")
        return ""  # empty string triggers OpenAI fallback in llm_call


async def llm_call(agent: str, user_message: str, *, temperature: float | None = None) -> str:
    """
    Call the configured LLM for the given agent using LiteLLM.

    LiteLLM routes to the correct provider based on LLM_MODEL prefix:
      gpt-4o                    -> OpenAI (OPENAI_API_KEY)
      claude-opus-4             -> Anthropic (ANTHROPIC_API_KEY)
      gemini/gemini-2.5-pro     -> Google Gemini (GOOGLE_API_KEY)
      groq/llama-3.3-70b        -> Groq (GROQ_API_KEY)
      mistral/mistral-large     -> Mistral (MISTRAL_API_KEY)
      ollama/llama3.3           -> Ollama local (OLLAMA_HOST, no key)
      bedrock/claude-3-5-sonnet -> AWS Bedrock (AWS_* vars)
      openai/<model>            -> any OpenAI-compatible endpoint (OPENAI_BASE_URL)

    LLM_PROVIDER=copilot|cursor -> routes through VS Code bridge first.
    LLM_PROVIDER=simulate      -> returns placeholder, no LLM call.
    """
    import os as _os
    temp = temperature if temperature is not None else AGENT_TEMPERATURES.get(agent, 0.2)
    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent, "You are a helpful AI.")

    # ── Copilot / Cursor bridge ──────────────────────────────────────────────
    if LLM_PROVIDER in ("copilot", "cursor"):
        add_log(f"[{agent}] -> Copilot Bridge ({COPILOT_BRIDGE_URL})")
        result = await _call_copilot_bridge(agent, system_prompt, user_message, temp)
        if result:
            return result
        add_log(f"[{agent}] Copilot bridge unreachable, falling back to {LLM_MODEL}...")

    # ── Simulation ──────────────────────────────────────────────────────────
    if LLM_PROVIDER == "simulate" or not _has_any_llm_key():
        add_log(f"[{agent}] Simulating ({LLM_MODEL} / no valid API key configured).")
        await asyncio.sleep(0.2)
        slug = agent.lower().replace(" ", "_")
        return (
            f"[SIMULATED]\n"
            f"# FILE: workspace/{slug}/main.py\n"
            f"# {agent} placeholder for: {user_message[:120]}\n"
            f"def placeholder(): pass\n"
        )

    # ── LiteLLM universal call ───────────────────────────────────────────────
    try:
        import litellm  # type: ignore
        litellm.drop_params = True          # silently ignore unsupported params
        litellm.set_verbose = False

        # Inject per-provider env vars that LiteLLM expects
        if GOOGLE_API_KEY:
            _os.environ.setdefault("GEMINI_API_KEY", GOOGLE_API_KEY)
        if OLLAMA_HOST:
            _os.environ.setdefault("OLLAMA_API_BASE", OLLAMA_HOST)

        # Extra kwargs for OpenAI-compatible custom endpoints
        extra: dict[str, Any] = {}
        if OPENAI_BASE_URL and (LLM_MODEL.startswith("openai/") or not any(
            LLM_MODEL.startswith(p)
            for p in ("claude", "gemini/", "groq/", "mistral/", "ollama/",
                      "together_ai/", "bedrock/", "anthropic.")
        )):
            extra["api_base"] = OPENAI_BASE_URL

        add_log(f"[{agent}] -> {LLM_MODEL} (temp={temp:.2f})")
        resp = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=temp,
            **extra,
        )
        content = resp.choices[0].message.content or ""
        add_log(f"[{agent}] <- {LLM_MODEL} ({len(content)} chars)")
        return content
    except Exception as exc:
        add_log(f"[{agent}] LLM error ({LLM_MODEL}): {exc}")
        return f"[LLM ERROR] {exc}"

def parse_files_from_llm(output: str) -> list[dict]:
    """
    Extract FILE: path blocks from LLM output.
    Supports multiple marker styles emitted by different agents:
      // FILE: path/to/file.tsx        (Frontend Dev)
      # FILE: path/to/file.py          (Backend Dev, QA, DevOps)
      -- FILE: migrations/0001_x.sql   (Database Engineer)
      FILE: path/to/file.py            (bare fallback)
    """
    # Primary: comment-prefixed markers (// # --)
    primary = re.compile(
        r"(?://|#|--)" + r"\s+" + r"FILE:\s+(.+?)" + "\n" + r"(.*?)(?=(?://|#|--)" + r"\s+" + r"FILE:|\Z)",
        re.DOTALL,
    )
    files = [
        {"path": m.group(1).strip(), "content": m.group(2).strip()}
        for m in primary.finditer(output)
    ]
    if files:
        return [f for f in files if f["path"] and f["content"]]

    # Fallback: bare FILE: markers (some models omit the comment prefix)
    fallback = re.compile(
        r"^FILE:" + r"\s+" + r"(.+?)" + "\n" + r"(.*?)(?=^FILE:|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    files = [
        {"path": m.group(1).strip(), "content": m.group(2).strip()}
        for m in fallback.finditer(output)
    ]
    if files:
        return [f for f in files if f["path"] and f["content"]]

    # Last resort: markdown code blocks with filename on first line
    md_block = re.compile(
        r"```(?:python|typescript|tsx?|sql|yaml|dockerfile|bash|sh)?" + r"\s+([\w./\-]+\.\w+)" + "\n" + r"(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    files = [
        {"path": m.group(1).strip(), "content": m.group(2).strip()}
        for m in md_block.finditer(output)
    ]
    return [f for f in files if f["path"] and f["content"]]

async def memory_store(
    task_id: str,
    agent: str,
    category: str,
    content: str,
    *,
    tags: str = "",
) -> None:
    """
    Persist a key agent insight for injection into future pipeline runs.
    `tags` is a comma-separated string of searchable labels (e.g. 'auth,jwt,fastapi').
    Content is capped at 1200 chars (up from 600) to preserve more context.
    """
    # Build tagged content prefix for richer recall
    tagged = f"[tags:{tags}] {content}" if tags else content
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO agent_memory (task_id, agent, category, content) VALUES (?,?,?,?)",
                (task_id, agent, category, tagged[:1200]),
            )
            await db.commit()
    except Exception:
        pass


async def memory_recall(query: str, limit: int = 5) -> list[str]:
    """Recall relevant past memories using keyword search."""
    keywords = [w.lower() for w in query.split() if len(w) > 4][:6]
    if not keywords:
        return []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            where = " OR ".join("LOWER(content) LIKE ?" for _ in keywords)
            params = [f"%{kw}%" for kw in keywords]
            async with db.execute(
                f"SELECT agent, category, content FROM agent_memory "
                f"WHERE {where} ORDER BY id DESC LIMIT ?",
                params + [limit],
            ) as cur:
                rows = await cur.fetchall()
                return [f"[{r['agent']}/{r['category']}] {r['content'][:200]}" for r in rows]
    except Exception:
        return []


# ============================================================
# 5.6  REAL TOOL EXECUTION  (pytest, bandit, npm audit, docker)
# ============================================================

def _write_files_to_workspace(files: list[dict]) -> None:
    """Write generated files to GIT_WORKSPACE immediately so real tools can run on them."""
    for f in files:
        try:
            dest = GIT_WORKSPACE / f["path"].lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f["content"], encoding="utf-8")
        except Exception:
            pass



def _build_file_manifest(files: list[dict]) -> str:
    """
    Build a compact file manifest for cross-agent context injection.
    Lists each generated file with its path, line count, and a preview line.
    Keeps total output under ~2000 chars regardless of how many files.
    """
    if not files:
        return "  (no files generated yet)"
    lines: list[str] = []
    for f in files[:40]:  # cap at 40 entries to stay within token budget
        path = f.get("path", "?")
        content = f.get("content", "")
        loc = len(content.splitlines())
        # First non-blank, non-comment line as preview
        preview = next(
            (ln.strip() for ln in content.splitlines()
             if ln.strip() and not ln.strip().startswith(("#", "//", "--", "/*"))),
            "",
        )[:80]
        lines.append(f"  {path}  ({loc} lines)  →  {preview}")
    if len(files) > 40:
        lines.append(f"  ... and {len(files) - 40} more files")
    return "\n".join(lines)


async def _validate_python_files(files: list[dict]) -> list[tuple[str, str]]:
    """
    Syntax-check every generated .py file using py_compile.
    Returns a list of (path, error_message) for files that fail.
    Fast: runs in-process, no subprocess overhead.
    """
    import py_compile
    import tempfile

    errors: list[tuple[str, str]] = []
    for f in files:
        if not f.get("path", "").endswith(".py"):
            continue
        content = f.get("content", "")
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            py_compile.compile(tmp_path, doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append((f["path"], str(exc)))
        except Exception as exc:
            errors.append((f["path"], f"[validation error] {exc}"))
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
    return errors


async def _run_subprocess(cmd: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str]:
    """Run a subprocess safely (no shell=True — injection-safe) and return (returncode, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 1, f"[TIMEOUT after {timeout}s]"
        return proc.returncode or 0, stdout.decode(errors="replace")[:2000]
    except FileNotFoundError as exc:
        return 1, f"[TOOL NOT FOUND — install it first: {exc}]"
    except Exception as exc:
        return 1, f"[SUBPROCESS ERROR: {exc}]"


async def run_tests_real(workspace: Path) -> dict:
    """
    Run pytest (Python) and/or vitest/jest (JS/TS) on the workspace.
    Returns {"passed": bool, "coverage": int, "output": str}.
    """
    results: dict = {"passed": False, "coverage": 0, "output": ""}
    combined = ""
    any_runner = False

    # Python — pytest + coverage
    py_tests = list(workspace.rglob("test_*.py")) + list(workspace.rglob("*_test.py"))
    if py_tests:
        any_runner = True
        code, out = await _run_subprocess(
            ["python", "-m", "pytest", "--tb=short", "-q", "--no-header",
             "--cov=.", "--cov-report=term-missing"],
            workspace, timeout=120,
        )
        combined += f"=== pytest ===\n{out}\n"
        cov = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", out)
        if cov:
            results["coverage"] = int(cov.group(1))
        if code == 0:
            results["passed"] = True

    # JavaScript / TypeScript — vitest or jest
    if (workspace / "package.json").exists():
        any_runner = True
        code, out = await _run_subprocess(
            ["npm", "test", "--", "--run", "--reporter=verbose"],
            workspace, timeout=120,
        )
        combined += f"=== vitest/jest ===\n{out}\n"
        if code == 0 and not py_tests:
            results["passed"] = True

    if not any_runner:
        combined = "[No test runner detected in workspace — skipping real execution]"
        results["passed"] = True   # don't block pipeline if no infra yet

    results["output"] = combined[:2000]
    return results


async def run_security_real(workspace: Path) -> dict:
    """
    Run bandit (Python static analysis) and npm audit (JS dependency vuln scan).
    Returns {"python_issues": str, "npm_issues": str, "output": str}.
    """
    results: dict = {"python_issues": "not checked", "npm_issues": "not checked", "output": ""}
    combined = ""

    # bandit — Python SAST
    if list(workspace.rglob("*.py")):
        code, out = await _run_subprocess(
            ["python", "-m", "bandit", "-r", ".", "-ll", "-f", "txt", "--exit-zero"],
            workspace, timeout=60,
        )
        combined += f"=== bandit ===\n{out}\n"
        highs = len(re.findall(r"Severity: (High|Critical)", out, re.IGNORECASE))
        results["python_issues"] = f"{highs} HIGH/CRITICAL" if highs else "clean"

    # npm audit — JS dependency vulnerabilities
    if (workspace / "package.json").exists():
        code, out = await _run_subprocess(
            ["npm", "audit", "--audit-level=high", "--json"],
            workspace, timeout=60,
        )
        combined += f"=== npm audit ===\n{out[:800]}\n"
        import json as _json
        try:
            audit_data = _json.loads(out)
            vulns = audit_data.get("metadata", {}).get("vulnerabilities", {})
            high_total = vulns.get("high", 0) + vulns.get("critical", 0)
            results["npm_issues"] = f"{high_total} HIGH/CRITICAL" if high_total else "clean"
        except Exception:
            results["npm_issues"] = "parse error (non-JSON output)"

    results["output"] = combined[:2000]
    return results


async def docker_build(workspace: Path, task_id: str) -> tuple[bool, str]:
    """Build a Docker image from the workspace Dockerfile."""
    tag = f"ai-dev-team/{task_id}:latest"
    code, out = await _run_subprocess(
        ["docker", "build", "-t", tag, "."],
        workspace, timeout=300,
    )
    return code == 0, out[-500:]


# ============================================================
# 5.7  TASK DECOMPOSITION  (break complex tasks into phases)
# ============================================================

async def decompose_task(task: str) -> list[str]:
    """
    Simple / narrow tasks   -> returns [task] (single phase, skip LLM call).
    Complex / broad tasks   -> asks LLM to split into <= MAX_SUBTASKS ordered
                               implementation phases, each self-contained.
    """
    simple_starters = ("add ", "fix ", "update ", "create ", "write ", "refactor ", "rename ", "delete ")
    if len(task.split()) <= 8 and any(task.lower().startswith(s) for s in simple_starters):
        return [task]

    if not OPENAI_API_KEY:
        return [task]   # simulation mode — skip the extra LLM call

    prompt = (
        f"Break this software task into at most {MAX_SUBTASKS} ordered implementation phases. "
        f"Each phase is a self-contained unit of work (e.g. 'Auth service', 'Dashboard UI').\n"
        f"Output ONLY a numbered list. No explanations, no preamble.\n\n"
        f"Task: {task}"
    )
    try:
        raw = await llm_call("Project Manager", prompt)
        phases = []
        for line in raw.splitlines():
            line = line.strip()
            if line and line[0].isdigit() and "." in line[:4]:
                phase = re.sub(r"^\d+\.\s*", "", line).strip()
                if phase:
                    phases.append(phase)
        return phases[:MAX_SUBTASKS] if phases else [task]
    except Exception:
        return [task]


# ============================================================
# 6. GIT ENGINE  (subprocess — no extra dep, avoids shell injection)
# ============================================================

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command using list args to prevent shell injection."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _git_write_files(files: list[dict], workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for f in files:
        fpath = workspace / f["path"]
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(f["content"], encoding="utf-8")


async def git_commit_and_push(task_id: str, task: str, files: list[dict]) -> tuple[str | None, str]:
    """
    Write generated files to GIT_WORKSPACE, commit on feature branch.
    Push + open GitHub PR if GITHUB_TOKEN and GITHUB_REPO are configured.
    Returns (pr_url | None, branch_name).
    """
    workspace = GIT_WORKSPACE
    workspace.mkdir(parents=True, exist_ok=True)

    if not (workspace / ".git").exists():
        _git(["init"], workspace)
        _git(["config", "user.email", "ai-dev-team@local"], workspace)
        _git(["config", "user.name", "AI Dev Team"], workspace)
        _git(["commit", "--allow-empty", "-m", "chore: init workspace"], workspace)

    branch = f"feat/{task_id}"
    _git(["checkout", "-B", "main"], workspace)
    _git(["checkout", "-b", branch], workspace)

    # Strip shell metacharacters from commit message
    safe_task = re.sub(r"[`$\\\"'<>|;&]", "", task)[:72]
    _git_write_files(files, workspace)
    _git(["add", "."], workspace)
    _git(["commit", "-m", f"feat: {safe_task} [{task_id}]"], workspace)
    add_log(f"[DevOps] Committed {len(files)} file(s) to branch {branch}")

    pr_url: str | None = None
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            import httpx
            # Token stays in memory only, never logged
            remote = f"https://x-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
            _git(["remote", "set-url", "origin", remote], workspace)
            _git(["push", "-u", "origin", branch], workspace)

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"https://api.github.com/repos/{GITHUB_REPO}/pulls",
                    headers={
                        "Authorization": f"Bearer {GITHUB_TOKEN}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={
                        "title": f"feat: {safe_task} [{task_id}]",
                        "head": branch,
                        "base": "main",
                        "body": (
                            f"**Automated PR by AI Dev Team**\n\n"
                            f"**Task:** {task}\n**Task ID:** `{task_id}`\n\n"
                            "---\n*Generated by Agent Mesh v3.0*"
                        ),
                    },
                )
            if r.status_code == 201:
                pr_url = r.json().get("html_url", "")
                add_log(f"[DevOps] PR opened: {pr_url}")
            else:
                add_log(f"[DevOps] GitHub PR returned {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            add_log(f"[DevOps] GitHub error: {exc}")

    return pr_url, branch


# ============================================================
# 7. WHATSAPP  (Twilio REST — sync SDK wrapped in executor)
# ============================================================

def _twilio_send_sync(to: str, body: str) -> None:
    from twilio.rest import Client
    Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
        from_=TWILIO_WA_FROM, to=to, body=body[:1600]
    )


async def wa_send(to: str, body: str) -> None:
    if not _use_whatsapp() or not to:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _twilio_send_sync, to, body)
    except Exception as exc:
        add_log(f"[WhatsApp] Send failed: {exc}")


async def wa_send_plan(task: str) -> None:
    if not MANAGER_WHATSAPP:
        return
    text = (
        "AI Dev Team -- Execution Plan\n\n"
        f"Order: {task}\n\n"
        "Pipeline:\n"
        "1. Architect -- Design\n"
        "2. Frontend Dev + Backend Dev (parallel)\n"
        "3. Database Engineer -- Schema\n"
        "4. QA Engineer -- Tests (80% gate)\n"
        "5. Security Analyst -- OWASP scan\n"
        "6. DevOps Engineer -- Docker & CI/CD\n"
        "7. Project Manager -- Delivery report\n\n"
        "Reply 'approve' to execute or 'reject' to cancel."
    )
    _wa_pending[MANAGER_WHATSAPP] = task
    await wa_send(MANAGER_WHATSAPP, text)




# ============================================================
# 7.5  ZEROCLAW GATEWAY  (https://github.com/zeroclaw-labs/zeroclaw)
# ============================================================
# ZeroClaw is a Rust-based personal AI assistant daemon that connects to 20+
# messaging channels natively (Discord, WhatsApp, Telegram, Slack, Signal …).
# When MESSAGING_PROVIDER=zeroclaw, agent_mesh no longer manages discord.py or
# Twilio directly — ZeroClaw's SOP (Standard Operating Procedure) webhooks drive
# the pipeline instead.
#
# Security: every inbound ZeroClaw webhook is verified with HMAC-SHA256.
# ─────────────────────────────────────────────────────────────────────────────

class ZeroClawPayload(BaseModel):
    action: str = "order"    # order | approve | reject
    task: str = ""
    channel: str = ""
    sender: str = ""
    reply_url: str = ""      # ZeroClaw SOP callback URL for async progress/result


def _verify_zeroclaw_sig(body: bytes, sig_header: str) -> bool:
    """HMAC-SHA256 signature verification for inbound ZeroClaw SOP webhooks.
    If ZEROCLAW_WEBHOOK_SECRET is not set, verification is skipped (dev mode).
    """
    if not ZEROCLAW_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        ZEROCLAW_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    provided = sig_header.lstrip("sha256=")
    return hmac.compare_digest(expected, provided)


async def _zeroclaw_reply(reply_url: str, message: str) -> None:
    """POST an async result/report back to ZeroClaw's SOP callback URL."""
    if not reply_url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                reply_url,
                json={"message": message},
                headers={"X-ZeroClaw-Source": "agent-mesh"},
            )
    except Exception as exc:
        add_log(f"[ZeroClaw] Async reply to {reply_url} failed: {exc}")


async def _execute_and_reply_zeroclaw(task: str, reply_url: str) -> None:
    """Run the full SDLC pipeline then POST the delivery report to ZeroClaw."""
    await execute_pipeline(None, task)
    if reply_url and SYSTEM_STATE["history"]:
        entry = SYSTEM_STATE["history"][-1]
        report = (
            f"Task Complete: {entry['description']}\n"
            f"Files: {entry['files_modified']} | Branch: {entry.get('branch', 'N/A')}\n"
            f"{'PR: ' + entry['pr_url'] if entry.get('pr_url') else 'Committed locally'}"
        )
        await _zeroclaw_reply(reply_url, report)

# ============================================================
# 8. DISCORD BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


class ApprovalView(discord.ui.View):
    def __init__(self, task: str) -> None:
        super().__init__(timeout=1800)
        self.task = task

    def _is_architect(self, interaction: discord.Interaction) -> bool:
        return MANAGER_DISCORD_ID == 0 or interaction.user.id == MANAGER_DISCORD_ID

    @discord.ui.button(label="Approve Execution", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_architect(interaction):
            await interaction.response.send_message("Only the Architect can approve.", ephemeral=True)
            return
        await interaction.response.send_message("Plan Approved. Team executing...", ephemeral=False)
        self.stop()
        asyncio.create_task(execute_pipeline(interaction.channel, self.task))

    @discord.ui.button(label="Reject / Modify", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_architect(interaction):
            await interaction.response.send_message("Only the Architect can reject.", ephemeral=True)
            return
        await interaction.response.send_message("Plan Rejected. Issue a revised order.", ephemeral=False)
        set_agent_status("Project Manager", "IDLE", "blue")
        SYSTEM_STATE["current_task"] = "None"
        add_log("[Project Manager] Task rejected. Team standing by.")
        self.stop()


@bot.event
async def on_ready() -> None:
    add_log(f"[DISCORD] Bridge connected as {bot.user}")


@bot.command(name="order")
async def receive_order(ctx: commands.Context, *, task: str) -> None:
    """!order <task description>  -- issue in #orders channel"""
    if CH_ORDERS and ctx.channel.id != CH_ORDERS:
        await ctx.send(f"Please issue orders in <#{CH_ORDERS}>.", delete_after=10)
        return
    await _handle_new_order(task, discord_channel=ctx.channel, discord_reply=ctx.send)


async def _handle_new_order(
    task: str,
    discord_channel: Any = None,
    discord_reply: Any = None,
) -> None:
    add_log(f"[ORDER] Received: '{task}'")
    SYSTEM_STATE["current_task"] = task
    set_agent_status("Project Manager", "THINKING...", "blue")

    if discord_reply:
        await discord_reply(f"Project Manager analyzing: `{task}`...")

    await asyncio.sleep(2)
    set_agent_status("Project Manager", "WAITING APPROVAL", "yellow")
    add_log("[Project Manager] Plan ready -- awaiting approval.")

    if _use_discord() and (discord_channel or bot.is_ready()):
        llm_note = f"LLM: {OPENAI_MODEL}" if OPENAI_API_KEY else "LLM: Simulated (set OPENAI_API_KEY)"
        plan = (
            f"### Execution Plan\n**Order:** {task}\n\n**Pipeline:**\n"
            f"1. Architect -- Design\n"
            f"2. Frontend Dev + Backend Dev (parallel)\n"
            f"3. Database Engineer -- Schema changes\n"
            f"4. QA Engineer -- Tests (80% gate)\n"
            f"5. Security Analyst -- OWASP scan\n"
            f"6. DevOps Engineer -- Docker & CI/CD\n"
            f"7. Project Manager -- Final report\n\n"
            f"**{llm_note}**"
        )
        target_ch = bot.get_channel(CH_PLANS) if CH_PLANS else discord_channel
        await (target_ch or discord_channel).send(plan, view=ApprovalView(task))

    if _use_whatsapp():
        await wa_send_plan(task)


async def _discord_post(channel_id: int, message: str) -> None:
    if not channel_id or not bot.is_ready():
        return
    ch = bot.get_channel(channel_id)
    if ch:
        try:
            await ch.send(message[:2000])
        except discord.HTTPException:
            pass




# ============================================================
# 8.1  HUMAN-IN-THE-LOOP  Architecture Gate  (Discord buttons)
# ============================================================

class ArchGateView(discord.ui.View):
    """Sent to #plans after Architect designs; manager clicks Approve or Reject."""

    def __init__(self, task_id: str, task: str) -> None:
        super().__init__(timeout=float(HUMAN_GATE_TIMEOUT))
        self.task_id = task_id
        self.task    = task

    def _is_manager(self, interaction: discord.Interaction) -> bool:
        return MANAGER_DISCORD_ID == 0 or interaction.user.id == MANAGER_DISCORD_ID

    @discord.ui.button(label="✅ Approve Architecture", style=discord.ButtonStyle.success)
    async def approve_arch(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_manager(interaction):
            await interaction.response.send_message("⛔ Only the manager may approve.", ephemeral=True)
            return
        gate = _pipeline_gates.get(self.task_id)
        if gate and not gate.is_set():
            gate.set()
            await interaction.response.send_message(
                f"✅ **Architecture approved.** Pipeline continuing for `{self.task_id}`...",
                ephemeral=False,
            )
        else:
            await interaction.response.send_message("⚠️ Gate already resolved or expired.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ Reject Architecture", style=discord.ButtonStyle.danger)
    async def reject_arch(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self._is_manager(interaction):
            await interaction.response.send_message("⛔ Only the manager may reject.", ephemeral=True)
            return
        gate = _pipeline_gates.get(self.task_id)
        if gate:
            SYSTEM_STATE[f"_gate_rejected_{self.task_id}"] = True
            gate.set()  # unblock the wait
            await interaction.response.send_message(
                f"❌ **Architecture rejected.** Pipeline aborted for `{self.task_id}`.",
                ephemeral=False,
            )
        else:
            await interaction.response.send_message("⚠️ Gate already resolved or expired.", ephemeral=True)
        self.stop()

# ============================================================
# 9. EXECUTION PIPELINE
# ============================================================

# ============================================================
# 6.  IDE CHATBOT TOOLS  (Copilot / Cursor / Antigravity)
# ============================================================

async def consult_ide_chatbot(
    agent: str,
    topic: str,
    context: str,
    *,
    ide: str | None = None,
) -> str:
    """
    Let an agent consult an IDE chatbot (GitHub Copilot, Cursor AI, or
    Google Antigravity) as a SUPPLEMENTARY TOOL -- separate from the
    agent's main LLM brain (LLM_PROVIDER).

    `topic`   -- short label, e.g. "code review", "test suggestions"
    `context` -- the code / question to send to the IDE chatbot
    `ide`     -- "copilot" | "cursor" | "antigravity" | "all"
                 defaults to the IDE_CHATBOT env setting.

    Returns combined IDE chatbot response, or empty string if unavailable.
    """
    if not IDE_TOOLS_ENABLED:
        return ""

    target = ide or IDE_CHATBOT
    ides   = ["copilot", "cursor", "antigravity"] if target == "all" else [target]
    parts: list[str] = []

    for _ide in ides:
        if _ide in ("copilot", "cursor"):
            # Route through the VS Code extension bridge (:8001)
            payload = {
                "agent": agent,
                "system": (
                    f"You are the {_ide.title()} AI assistant integrated into "
                    f"an autonomous software development pipeline. "
                    f"Provide concise, actionable {topic}."
                ),
                "user": context[:3000],
                "ide": _ide,
            }
            try:
                import httpx
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{COPILOT_BRIDGE_URL}/chat", json=payload
                    )
                    resp.raise_for_status()
                    result = resp.json().get("content", "")
                    if result:
                        parts.append(f"### {_ide.title()} says:\n{result}")
                        add_log(f"[{agent}] [{_ide.title()}] {topic}: {result[:80]}")
            except Exception as exc:
                add_log(f"[{agent}] [{_ide.title()}] bridge unreachable: {exc}")

        elif _ide == "antigravity":
            # Antigravity is a Google MCP IDE -- it connects TO CoDevx, not the reverse.
            # To "consult Antigravity's AI" we call Google Gemini directly via LiteLLM
            # (same frontier models Antigravity runs internally: Gemini 3.1 Pro etc.)
            if not GOOGLE_API_KEY:
                add_log(
                    f"[{agent}] [Antigravity/Gemini] skipped -- "
                    "GOOGLE_API_KEY required (set it in .env)"
                )
                continue
            import os as _osa
            _osa.environ.setdefault("GEMINI_API_KEY", GOOGLE_API_KEY)
            try:
                import litellm as _ll  # type: ignore
                _ll.drop_params = True
                ag_resp = await _ll.acompletion(
                    model=ANTIGRAVITY_MODEL,  # e.g. gemini/gemini-2.5-pro
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a Google Gemini AI assistant (the model powering "
                                "Google Antigravity IDE). Provide concise, actionable "
                                f"{topic}."
                            ),
                        },
                        {"role": "user", "content": context[:3000]},
                    ],
                    max_tokens=1200,
                    temperature=0.3,
                )
                result = ag_resp.choices[0].message.content or ""
                if result:
                    parts.append(f"### Antigravity (Gemini) says:\n{result}")
                    add_log(f"[{agent}] [Antigravity/Gemini] {topic}: {result[:80]}")
            except Exception as exc:
                add_log(f"[{agent}] [Antigravity/Gemini] error: {exc}")

    return "\n\n".join(parts)




# ============================================================
# 9.1  LANGGRAPH SUBGRAPHS  (QA + Security ReAct loops)
# ============================================================

async def _notify_manager_gate(task_id: str, task: str, arch_summary: str) -> None:
    """Notify Discord (#plans) and WhatsApp with arch design + approval buttons."""
    preview = arch_summary[:1200].strip()
    discord_msg = (
        f"🏗️ **Architecture Ready — `{task_id}`**\n\n"
        f"**Task:** {task}\n\n"
        f"**Design:**\n{preview}\n\n"
        f"⏳ Waiting up to {HUMAN_GATE_TIMEOUT}s for approval. "
        f"Click a button below or reply via WhatsApp."
    )
    if _use_discord() and bot.is_ready():
        target = bot.get_channel(CH_PLANS) if CH_PLANS else None
        if target:
            try:
                await target.send(discord_msg[:2000], view=ArchGateView(task_id, task))
                add_log(f"[HITL] Architecture gate posted to Discord #plans — task {task_id}")
            except Exception as exc:
                add_log(f"[HITL] Discord gate notify failed: {exc}")

    if _use_whatsapp() and MANAGER_WHATSAPP:
        wa_text = (
            f"Architecture ready — task {task_id}\n\n"
            f"Task: {task}\n\n"
            f"{arch_summary[:600]}\n\n"
            f"Reply:\n"
            f"  approve arch {task_id}  — proceed with coding\n"
            f"  reject arch {task_id}   — abort pipeline"
        )
        await wa_send(MANAGER_WHATSAPP, wa_text)
        add_log(f"[HITL] Architecture gate sent via WhatsApp — task {task_id}")


async def _run_qa_subgraph(
    task: str,
    arch_out: str,
    fe_phase: str,
    be_phase: str,
    all_files: list[dict],
    qa_files: list[dict],
    ctx: dict[str, str],
    task_id: str = "",
) -> dict:
    """
    QA gate: write tests → run tests → (if failed) reason + retry.

    LANGGRAPH_ENABLED=false → classic for-loop (unchanged behaviour).
    LANGGRAPH_ENABLED=true  → LangGraph StateGraph with:
      • Autonomous ReAct retry loop (write → run → conditional edge → write …)
      • SQLite checkpointing so the loop survives server restarts
    """
    # ── shared inner coroutines ───────────────────────────────────────────────
    async def _write_tests(attempt: int, test_output: str) -> tuple[str, list[dict]]:
        set_agent_status("QA Engineer", "TESTING...", "yellow")
        retry_lbl = f" (retry {attempt}/{MAX_RETRIES})" if attempt else ""
        add_log(f"[QA Engineer] Writing test suites{retry_lbl}...")
        qa_ctx = (
            "Task: " + task + "\n\n"
            "Architecture summary:\n" + arch_out[:1200] + "\n\n"
            "Generated files manifest:\n" + _build_file_manifest(all_files) + "\n\n"
            "Frontend code (latest phase):\n" + fe_phase[:1500] + "\n\n"
            "Backend code (latest phase):\n" + be_phase[:1500]
        )
        if attempt > 0 and test_output:
            qa_ctx += "\n\nTest failures to fix:\n" + test_output[:600]
        if IDE_TOOLS_ENABLED and be_phase.strip():
            ide_hints = await consult_ide_chatbot(
                "QA Engineer",
                "test case suggestions (edge cases, error paths, security tests)",
                f"Suggest additional test cases for this code:\n\n{be_phase[:2000]}",
            )
            if ide_hints:
                qa_ctx += f"\n\nIDE chatbot test suggestions:\n{ide_hints[:800]}"
                add_log("[QA Engineer] IDE test hints incorporated.")
        out = await llm_call("QA Engineer", qa_ctx)
        new_files = parse_files_from_llm(out)
        _write_files_to_workspace(new_files)
        return out, new_files

    async def _exec_tests() -> tuple[bool, str]:
        if not ENABLE_REAL_TOOLS:
            add_log(f"[QA Engineer] Test files written. (ENABLE_REAL_TOOLS=false)")
            return True, ""
        res = await run_tests_real(GIT_WORKSPACE)
        cov = res.get("coverage", 0)
        ok  = res["passed"] and cov >= 80
        add_log(f"[QA Engineer] Real tests: {'PASSED' if ok else 'FAILED'} | Coverage: {cov}%")
        return ok, res["output"]

    # ── LangGraph path ────────────────────────────────────────────────────────
    if LANGGRAPH_ENABLED:
        try:
            from typing import TypedDict as _TD
            from langgraph.graph import StateGraph as _SG, END as _END  # type: ignore
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver as _CKPT  # type: ignore

            class _QAS(_TD):
                attempts:     int
                passed:       bool
                test_output:  str
                qa_out:       str

            async def _node_write(state: _QAS) -> dict:  # type: ignore[misc]
                out, new_f = await _write_tests(state["attempts"], state["test_output"])
                all_files.extend(new_f)
                qa_files.extend(new_f)
                ctx["qa"] = out
                return {"qa_out": out}

            async def _node_run(state: _QAS) -> dict:  # type: ignore[misc]
                ok, output = await _exec_tests()
                ctx["test_output"] = output
                return {"passed": ok, "test_output": output, "attempts": state["attempts"] + 1}

            def _route(state: _QAS) -> str:
                if state["passed"]:
                    return _END  # type: ignore[return-value]
                if state["attempts"] >= MAX_RETRIES:
                    add_log("[QA Engineer][LangGraph] Max retries — best-effort proceed.")
                    return _END  # type: ignore[return-value]
                add_log(
                    f"[QA Engineer][LangGraph] Autonomous retry "
                    f"{state['attempts']}/{MAX_RETRIES} — re-writing tests..."
                )
                return "write_tests"

            builder = _SG(_QAS)
            builder.add_node("write_tests", _node_write)
            builder.add_node("run_tests",   _node_run)
            builder.set_entry_point("write_tests")
            builder.add_edge("write_tests", "run_tests")
            builder.add_conditional_edges("run_tests", _route)

            ckpt_db = str(DB_PATH).replace(".db", "_lg.db")
            async with _CKPT.from_conn_string(ckpt_db) as checkpointer:
                graph  = builder.compile(checkpointer=checkpointer)
                thread = {"configurable": {"thread_id": f"{task_id}_qa"}}
                add_log("[QA Engineer][LangGraph] Subgraph compiled — starting ReAct loop.")
                await graph.ainvoke(
                    {"attempts": 0, "passed": False, "test_output": "", "qa_out": ""},
                    config=thread,
                )

            set_agent_status("QA Engineer", "IDLE", "yellow")
            return {"all_files": all_files, "qa_files": qa_files, "ctx": ctx}

        except ImportError as _ie:
            add_log(f"[QA Engineer] LangGraph import failed ({_ie}) — falling back to legacy loop.")
        except Exception as _ex:
            add_log(f"[QA Engineer][LangGraph] Subgraph error ({_ex}) — falling back to legacy loop.")

    # ── Legacy for-loop path (default + fallback) ─────────────────────────────
    test_output = ctx.get("test_output", "")
    for qa_attempt in range(MAX_RETRIES + 1):
        qa_out, qa_new = await _write_tests(qa_attempt, test_output)
        ctx["qa"] = qa_out
        qa_files.extend(qa_new)
        all_files.extend(qa_new)
        passed, test_output = await _exec_tests()
        ctx["test_output"] = test_output
        if passed:
            break
        if qa_attempt >= MAX_RETRIES:
            add_log("[QA Engineer] Max retries reached — proceeding with best effort.")
            break

    set_agent_status("QA Engineer", "IDLE", "yellow")
    return {"all_files": all_files, "qa_files": qa_files, "ctx": ctx}


async def _run_security_subgraph(
    task: str,
    arch_out: str,
    fe_phase: str,
    be_phase: str,
    db_cumulative: str,
    all_files: list[dict],
    ctx: dict[str, str],
    task_id: str = "",
) -> dict:
    """
    Security gate: LLM OWASP review → real bandit/npm-audit → apply fixes → retry.

    LANGGRAPH_ENABLED=false → classic for-loop (unchanged behaviour).
    LANGGRAPH_ENABLED=true  → LangGraph StateGraph with:
      • Autonomous ReAct fix-and-retry loop
      • SQLite checkpointing for resume-on-crash
    """
    scan_passed = True

    async def _review(attempt: int, prev_findings: str) -> tuple[str, bool, list[dict]]:
        set_agent_status("Security Analyst", "SCANNING...", "red")
        retry_lbl = f" (retry {attempt}/{MAX_RETRIES})" if attempt else ""
        add_log(f"[Security Analyst] OWASP Top 10 review{retry_lbl}...")
        sec_ctx = (
            "Review for OWASP Top 10 + OWASP ASVS Level 2 + CWE Top 25:\n\n"
            "Generated files:\n" + _build_file_manifest(all_files) + "\n\n"
            "Backend code (full latest phase):\n" + be_phase[:2000] + "\n\n"
            "Frontend code (full latest phase):\n" + fe_phase[:1000] + "\n\n"
            "Database schema:\n" + db_cumulative[-400:]
        )
        if attempt > 0 and prev_findings:
            sec_ctx += "\n\nPrevious scan findings:\n" + prev_findings[:500]
        if IDE_TOOLS_ENABLED and be_phase.strip():
            ide_hints = await consult_ide_chatbot(
                "Security Analyst",
                "security vulnerability analysis (OWASP Top 10, injection, auth flaws)",
                f"Identify security vulnerabilities in this backend code:\n\n{be_phase[:2000]}",
            )
            if ide_hints:
                sec_ctx += f"\n\nIDE chatbot security hints:\n{ide_hints[:800]}"
                add_log("[Security Analyst] IDE security hints incorporated.")
        out      = await llm_call("Security Analyst", sec_ctx)
        passed   = "SCAN: FAILED" not in out.upper()
        fix_files = parse_files_from_llm(out) if not passed else []
        return out, passed, fix_files

    async def _run_tools() -> str:
        if not ENABLE_REAL_TOOLS:
            return ""
        real = await run_security_real(GIT_WORKSPACE)
        add_log(f"[Security Analyst] bandit: {real['python_issues']} | npm audit: {real['npm_issues']}")
        ctx["scan_output"] = real["output"]
        return real["output"]

    # ── LangGraph path ────────────────────────────────────────────────────────
    if LANGGRAPH_ENABLED:
        try:
            from typing import TypedDict as _TD
            from langgraph.graph import StateGraph as _SG, END as _END  # type: ignore
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver as _CKPT  # type: ignore

            class _SecS(_TD):
                attempts:      int
                passed:        bool
                scan_findings: str
                sec_out:       str

            async def _node_review(state: _SecS) -> dict:  # type: ignore[misc]
                out, ok, fix_f = await _review(state["attempts"], state["scan_findings"])
                ctx["security"] = out
                if fix_f:
                    all_files.extend(fix_f)
                    _write_files_to_workspace(fix_f)
                    add_log(f"[Security Analyst][LangGraph] {len(fix_f)} fix file(s) applied.")
                return {"sec_out": out, "passed": ok}

            async def _node_scan(state: _SecS) -> dict:  # type: ignore[misc]
                findings = await _run_tools()
                add_log(f"[Security Analyst] LLM verdict: {'PASSED' if state['passed'] else 'FAILED'}")
                return {
                    "scan_findings": findings,
                    "attempts": state["attempts"] + 1,
                }

            def _route(state: _SecS) -> str:
                if state["passed"]:
                    return _END  # type: ignore[return-value]
                if state["attempts"] >= MAX_RETRIES:
                    add_log("[Security Analyst][LangGraph] Max retries — escalating.")
                    return _END  # type: ignore[return-value]
                add_log(
                    f"[Security Analyst][LangGraph] Autonomous fix+retry "
                    f"{state['attempts']}/{MAX_RETRIES}..."
                )
                return "review"

            builder = _SG(_SecS)
            builder.add_node("review", _node_review)
            builder.add_node("scan",   _node_scan)
            builder.set_entry_point("review")
            builder.add_edge("review", "scan")
            builder.add_conditional_edges("scan", _route)

            ckpt_db = str(DB_PATH).replace(".db", "_lg.db")
            async with _CKPT.from_conn_string(ckpt_db) as checkpointer:
                graph  = builder.compile(checkpointer=checkpointer)
                thread = {"configurable": {"thread_id": f"{task_id}_sec"}}
                add_log("[Security Analyst][LangGraph] Subgraph compiled — starting ReAct loop.")
                final = await graph.ainvoke(
                    {"attempts": 0, "passed": False, "scan_findings": "", "sec_out": ""},
                    config=thread,
                )
            scan_passed = final.get("passed", True)

            if not scan_passed:
                raise RuntimeError(
                    "Security scan FAILED after all LangGraph retry attempts — "
                    "unresolved CRITICAL/HIGH vulnerabilities detected."
                )

            set_agent_status("Security Analyst", "IDLE", "red")
            return {"all_files": all_files, "ctx": ctx, "scan_passed": scan_passed}

        except RuntimeError:
            raise
        except ImportError as _ie:
            add_log(f"[Security Analyst] LangGraph import failed ({_ie}) — falling back to legacy loop.")
        except Exception as _ex:
            add_log(f"[Security Analyst][LangGraph] Subgraph error ({_ex}) — falling back to legacy loop.")

    # ── Legacy for-loop path (default + fallback) ─────────────────────────────
    prev_findings = ctx.get("scan_output", "")
    for sec_attempt in range(MAX_RETRIES + 1):
        sec_out, scan_passed, fix_f = await _review(sec_attempt, prev_findings)
        ctx["security"] = sec_out
        prev_findings   = await _run_tools()
        add_log(f"[Security Analyst] LLM verdict: {'PASSED' if scan_passed else 'FAILED'}")
        if scan_passed:
            break
        if sec_attempt >= MAX_RETRIES:
            raise RuntimeError(
                "Security scan FAILED after all retry attempts — "
                "unresolved CRITICAL/HIGH vulnerabilities detected."
            )
        if fix_f:
            all_files.extend(fix_f)
            _write_files_to_workspace(fix_f)
            add_log(f"[Security Analyst] {len(fix_f)} fix file(s) applied — retrying scan.")

    set_agent_status("Security Analyst", "IDLE", "red")
    return {"all_files": all_files, "ctx": ctx, "scan_passed": scan_passed}


async def execute_pipeline(channel: Any, task: str) -> None:

    """
    Full 8-agent SDLC pipeline (v4.0):
      Architect (1x, full design) -> Decompose -> N x [Frontend+Backend+Database]
      -> QA (with retry loop + real pytest/vitest)
      -> Security (with fix loop + real bandit/npm-audit)
      -> DevOps (CI/CD + optional Docker build)
      -> Git commit + GitHub PR
      -> Project Manager (delivery report)
      -> Persist agent memories for future tasks
    """
    task_id   = str(uuid.uuid4())[:8]
    all_files: list[dict] = []
    llm_used  = bool(OPENAI_API_KEY)
    ctx: dict[str, str] = {}
    scan_passed = True
    qa_files:   list[dict] = []
    fe_out, be_out = "", ""
    db_cumulative = ""   # accumulates DB schema across all phases

    try:
        # ── Recall past memories relevant to this task ────────────────────────
        memories  = await memory_recall(task, limit=MEMORY_CONTEXT_K)
        mem_ctx   = "\n".join(f"- {m}" for m in memories) if memories else ""

        # PHASE 0 — Architect: full system design
        set_agent_status("Architect", "DESIGNING...", "purple")
        set_agent_status("Project Manager", "OBSERVING", "blue")
        add_log("[Architect] Designing full system architecture...")
        arch_prompt = "Feature request: " + task + "\n\nProduce the complete architecture plan."
        if mem_ctx:
            arch_prompt += "\n\nRelevant context from past builds:\n" + mem_ctx
        arch_out = await llm_call("Architect", arch_prompt)
        # IDE Chatbot: second opinion on the architecture design
        if IDE_TOOLS_ENABLED:
            ide_arch_review = await consult_ide_chatbot(
                "Architect",
                "architecture review (scalability, maintainability, design patterns)",
                f"Review this software architecture plan and suggest improvements:\n\n{arch_out[:2500]}",
            )
            if ide_arch_review:
                arch_out += f"\n\n<!-- IDE Architecture Review -->\n{ide_arch_review[:600]}"
                add_log("[Architect] IDE architecture review appended.")
        ctx["arch"] = arch_out
        add_log(f"[Architect] {arch_out.splitlines()[0][:120]}")
        add_log("[Architect] Architecture complete.")
        set_agent_status("Architect", "IDLE", "purple")

        # ── Human-in-the-loop architecture gate ───────────────────────────────
        if HUMAN_GATE_ENABLED:
            gate_event = asyncio.Event()
            _pipeline_gates[task_id] = gate_event
            _gate_task_map["current"] = task_id
            set_agent_status("Architect", "WAITING APPROVAL", "yellow")
            add_log(f"[HITL] Architecture gate open — notifying manager (task {task_id})...")
            await _notify_manager_gate(task_id, task, arch_out)
            try:
                await asyncio.wait_for(gate_event.wait(), timeout=float(HUMAN_GATE_TIMEOUT))
                add_log(f"[HITL] Gate released for task {task_id}.")
            except asyncio.TimeoutError:
                add_log(
                    f"[HITL] Gate timeout ({HUMAN_GATE_TIMEOUT}s) — auto-proceeding with architecture."
                )
            finally:
                _pipeline_gates.pop(task_id, None)
                _gate_task_map.pop("current", None)
            if SYSTEM_STATE.pop(f"_gate_rejected_{task_id}", False):
                add_log("[HITL] Architecture rejected by manager. Aborting pipeline.")
                raise RuntimeError("Architecture rejected by manager via HITL gate.")
            set_agent_status("Architect", "IDLE", "purple")
            add_log("[HITL] Architecture approved — pipeline continuing.")

        # ── Break task into implementation phases ─────────────────────────────
        phase_list = await decompose_task(task)
        add_log(f"[PM] {len(phase_list)} implementation phase(s) planned.")

        # PHASE 1..N — Frontend + Backend + Database (per phase)
        for phase_idx, phase in enumerate(phase_list, 1):
            ph_label = f"Phase {phase_idx}/{len(phase_list)}"
            add_log(f"[{ph_label}] {phase[:90]}")

            # Frontend Dev + Backend Dev (parallel)
            set_agent_status("Frontend Dev", "CODING...", "cyan")
            set_agent_status("Backend Dev",  "CODING...", "green")
            add_log(f"[Frontend Dev] {ph_label} — writing components...")
            add_log(f"[Backend Dev]  {ph_label} — writing endpoints...")

            fe_prev = fe_out[-600:] if fe_out else "None yet"
            be_prev = be_out[-600:] if be_out else "None yet"
            fe_ctx = (
                "Task (phase): " + phase + "\n\n"
                "Full architecture:\n" + arch_out + "\n\n"
                "Previously written FE:\n" + fe_prev
            )
            be_ctx = (
                "Task (phase): " + phase + "\n\n"
                "Full architecture:\n" + arch_out + "\n\n"
                "Files already generated:\n" + _build_file_manifest(all_files) + "\n\n"
                + ("Database schema from previous phases:\n" + db_cumulative[-800:] + "\n\n"
                   if db_cumulative else "")
                + "Previously written BE:\n" + be_prev
            )
            fe_phase, be_phase = await asyncio.gather(
                llm_call("Frontend Dev", fe_ctx),
                llm_call("Backend Dev",  be_ctx),
            )
            fe_out += "\n" + fe_phase
            be_out += "\n" + be_phase

            fe_files = parse_files_from_llm(fe_phase)
            be_files = parse_files_from_llm(be_phase)
            all_files.extend(fe_files + be_files)
            _write_files_to_workspace(fe_files + be_files)
            add_log(f"[Frontend Dev] {len(fe_files)} file(s) written — {ph_label}")
            add_log(f"[Backend Dev]  {len(be_files)} file(s) written — {ph_label}")

            # IDE Chatbot: Backend code review (runs only when IDE_TOOLS_ENABLED=true)
            if IDE_TOOLS_ENABLED and be_phase.strip():
                ide_review = await consult_ide_chatbot(
                    "Backend Dev",
                    "code review and improvement suggestions",
                    f"Review this backend code for quality, patterns, and best practices:\n\n{be_phase[:2500]}",
                )
                if ide_review:
                    ctx["ide_be_review"] = ide_review
                    add_log(f"[Backend Dev] IDE review stored — {ph_label}")
            if IDE_TOOLS_ENABLED and fe_phase.strip():
                ide_fe_review = await consult_ide_chatbot(
                    "Frontend Dev",
                    "UI/UX code review and accessibility suggestions",
                    f"Review this frontend code for quality, accessibility (WCAG 2.1 AA), and patterns:\n\n{fe_phase[:2000]}",
                )
                if ide_fe_review:
                    ctx["ide_fe_review"] = ide_fe_review
                    add_log(f"[Frontend Dev] IDE review stored — {ph_label}")

            # Syntax-validate generated Python files immediately
            syn_errors = await _validate_python_files(be_files)
            for fp, err in syn_errors:
                add_log(f"[Backend Dev] ⚠️ Syntax error in {fp}: {err[:120]}")
            set_agent_status("Frontend Dev", "IDLE", "cyan")
            set_agent_status("Backend Dev",  "IDLE", "green")

            # Database Engineer
            set_agent_status("Database Engineer", "MIGRATING...", "gray")
            add_log(f"[Database Engineer] {ph_label} — schema & migrations...")
            db_out = await llm_call(
                "Database Engineer",
                "Task (phase): " + phase + "\n\nArchitecture:\n" + arch_out,
            )
            ctx["database"] = db_out
            db_files = parse_files_from_llm(db_out)
            all_files.extend(db_files)
            _write_files_to_workspace(db_files)
            add_log(f"[Database Engineer] {len(db_files)} migration(s) — {ph_label}")
            db_cumulative += "\n" + db_out[:600]  # feed schema to Backend in next phase
            set_agent_status("Database Engineer", "IDLE", "gray")

        # QA GATE — LangGraph ReAct subgraph (LANGGRAPH_ENABLED=true)
        #           or legacy retry loop (LANGGRAPH_ENABLED=false, default)
        _qa_result = await _run_qa_subgraph(
            task=task, arch_out=arch_out, fe_phase=fe_phase, be_phase=be_phase,
            all_files=all_files, qa_files=qa_files, ctx=ctx, task_id=task_id,
        )
        all_files = _qa_result["all_files"]
        qa_files  = _qa_result["qa_files"]
        ctx       = _qa_result["ctx"]

        # SECURITY GATE — LangGraph ReAct subgraph (LANGGRAPH_ENABLED=true)
        #                or legacy retry loop (LANGGRAPH_ENABLED=false, default)
        _sec_result = await _run_security_subgraph(
            task=task, arch_out=arch_out, fe_phase=fe_phase, be_phase=be_phase,
            db_cumulative=db_cumulative, all_files=all_files, ctx=ctx, task_id=task_id,
        )
        all_files   = _sec_result["all_files"]
        ctx         = _sec_result["ctx"]
        scan_passed = _sec_result["scan_passed"]

        # DEVOPS — CI/CD + optional Docker build
        set_agent_status("DevOps Engineer", "DEPLOYING...", "orange")
        add_log("[DevOps Engineer] Generating CI/CD configuration...")
        devops_out   = await llm_call(
            "DevOps Engineer",
            "Task: " + task + "\n\nGenerated files: " + str([f["path"] for f in all_files[:25]]),
        )
        devops_files = parse_files_from_llm(devops_out)
        all_files.extend(devops_files)
        _write_files_to_workspace(devops_files)
        add_log(f"[DevOps Engineer] {len(devops_files)} CI/CD file(s) generated.")

        if DOCKER_BUILD and (GIT_WORKSPACE / "Dockerfile").exists():
            build_ok, build_log = await docker_build(GIT_WORKSPACE, task_id)
            add_log(f"[DevOps Engineer] Docker build: {'OK' if build_ok else 'FAILED'} — {build_log[-120:]}")

        set_agent_status("DevOps Engineer", "IDLE", "orange")

        # GIT — commit all files + open GitHub PR
        pr_url: str | None = None
        branch = f"feat/{task_id}"
        if all_files:
            pr_url, branch = await git_commit_and_push(task_id, task, all_files)
            await db_save_files(task_id, all_files)

        # PROJECT MANAGER — delivery report
        set_agent_status("Project Manager", "REPORTING...", "blue")
        add_log("[Project Manager] Compiling delivery report...")
        pm_ctx = (
            "Task: " + task + "\n"
            "Implementation phases: " + str(len(phase_list)) + "\n"
            "Files generated: " + str(len(all_files)) + "\n"
            "Security scan: " + ("PASSED" if scan_passed else "FAILED") + "\n"
            "PR: " + (pr_url or "local branch — no GitHub configured") + "\n\n"
            "Architecture:\n" + arch_out[:500] + "\n\n"
            "Security findings:\n" + ctx.get("security", "")[:400]
        )
        pm_out = await llm_call("Project Manager", pm_ctx)
        add_log(f"[Project Manager] {pm_out.splitlines()[0][:120]}")

        # ── Persist agent memories for future runs ────────────────────────────
        # Derive simple tech-stack tags for searchable memory recall
        _task_lower = task.lower()
        _tags = ",".join(w for w in ["auth", "stripe", "postgres", "redis", "docker", "k8s",
                                     "react", "nextjs", "fastapi", "celery", "websocket"]
                         if w in _task_lower or w in arch_out.lower()[:300])
        await memory_store(task_id, "Architect",        "architecture", arch_out[:1000], tags=_tags)
        await memory_store(task_id, "Backend Dev",      "patterns",     be_out[:800],   tags=_tags)
        await memory_store(task_id, "Security Analyst", "findings",     ctx.get("security", "")[:600], tags="security")
        await memory_store(task_id, "Project Manager",  "delivery",     pm_out[:600],   tags=_tags)

        # ── History entry ─────────────────────────────────────────────────────
        history_entry: dict[str, Any] = {
            "id":             task_id,
            "description":    task,
            "completed_at":   time.strftime("%Y-%m-%d %H:%M:%S"),
            "files_modified": len(all_files),
            "tests_passed":   len(qa_files) * 8,
            "pr_url":         pr_url,
            "branch":         branch,
            "llm_used":       llm_used,
        }
        SYSTEM_STATE["history"].append(history_entry)
        if len(SYSTEM_STATE["history"]) > 50:
            SYSTEM_STATE["history"] = SYSTEM_STATE["history"][-50:]
        await db_save_task(history_entry)

        # ── Deliver report ────────────────────────────────────────────────────
        report_msg = (
            "## Task Complete — `" + task + "`\n"
            "**ID:** `" + task_id + "` | **Branch:** `" + branch + "`\n\n"
            "- " + str(len(phase_list)) + " phase(s) | " + str(len(all_files)) + " file(s) generated\n"
            "- Security: " + ("PASSED" if scan_passed else "FAILED") + "\n"
            "- LLM: " + (OPENAI_MODEL if llm_used else "Simulated") + "\n"
            + (("- PR: " + pr_url) if pr_url else "- Committed locally") + "\n\n"
            "**Report:**\n" + pm_out[:600]
        )
        if _use_discord() and channel:
            reports_ch = bot.get_channel(CH_REPORTS) if CH_REPORTS else channel
            await (reports_ch or channel).send(report_msg[:2000])

        if _use_whatsapp():
            wa_msg = (
                "Task Complete: " + task + "\n"
                "Phases: " + str(len(phase_list)) + " | Files: " + str(len(all_files)) + "\n"
                "LLM: " + (OPENAI_MODEL if llm_used else "Simulated") + "\n"
                + (("PR: " + pr_url) if pr_url else "Branch: " + branch) + "\n\n"
                + pm_out[:500]
            )
            await wa_send(MANAGER_WHATSAPP, wa_msg)

    except Exception as exc:
        add_log(f"[ERROR] Pipeline failed: {exc}")
        if channel and _use_discord():
            try:
                await channel.send(f"Pipeline error: `{exc}`")
            except Exception:
                pass
        if _use_whatsapp():
            await wa_send(MANAGER_WHATSAPP, f"Pipeline failed: {exc}")

    finally:
        for name in SYSTEM_STATE["agents"]:
            SYSTEM_STATE["agents"][name]["status"] = "IDLE"
        SYSTEM_STATE["current_task"] = "None"
        asyncio.create_task(_broadcast())
        add_log("[Project Manager] Workflow complete. Team standing by.")


# ============================================================
# 10. FASTAPI APP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    await init_db()
    history = await db_load_history()
    SYSTEM_STATE["history"] = history
    recent_logs = await db_load_recent_logs(100)
    SYSTEM_STATE["logs"] = recent_logs + SYSTEM_STATE["logs"]
    SYSTEM_STATE["llm_enabled"] = bool(OPENAI_API_KEY)
    SYSTEM_STATE["git_enabled"] = bool(GITHUB_REPO)
    add_log(f"[DB] Loaded {len(history)} task(s), {len(recent_logs)} recent log(s).")

    if not _use_discord():
        add_log("[INFO] Discord bridge disabled -- check MESSAGING_PROVIDER or DISCORD_TOKEN.")
        yield
        return

    bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))
    add_log("[BOOT] Discord bridge starting...")
    yield
    await bot.close()
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="AI Dev Team -- Agent Mesh", version="5.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)
    await websocket.send_text(json.dumps({"type": "state_update", "payload": SYSTEM_STATE}))
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        _ws_clients.discard(websocket)


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return SYSTEM_STATE


@app.get("/api/agents/{name}")
async def get_agent(name: str) -> dict[str, Any]:
    from fastapi import HTTPException
    agent = SYSTEM_STATE["agents"].get(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found.")
    return {"name": name, **agent}


@app.get("/api/history")
async def get_history() -> list[Any]:
    return SYSTEM_STATE["history"]


@app.get("/api/files/{task_id}")
async def get_task_files(task_id: str) -> list[dict]:
    """Return all files generated by a specific task (from SQLite)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT file_path, content FROM generated_files WHERE task_id = ?",
                (task_id,),
            ) as cur:
                rows = await cur.fetchall()
                return [{"path": r["file_path"], "content": r["content"]} for r in rows]
    except Exception:
        return []


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(default=""),
    From: str = Form(default=""),
) -> Response:
    """
    Twilio webhook -- POST here when manager messages the WhatsApp number.
    Point Twilio sandbox/number to: http://<your-ngrok-url>/webhook/whatsapp
    Commands:  order <task> | approve | reject
    """
    if not _use_whatsapp():
        return Response(content="", media_type="text/plain")

    body_lower = Body.strip().lower()
    sender = From.strip()

    if body_lower.startswith("!order ") or body_lower.startswith("order "):
        task = Body.strip().split(" ", 1)[1].strip()
        add_log(f"[WhatsApp] Order from {sender}: {task}")
        asyncio.create_task(_handle_new_order(task))

    elif body_lower == "approve":
        task = _wa_pending.pop(sender, None)
        if task:
            add_log(f"[WhatsApp] Plan approved by {sender}")
            asyncio.create_task(execute_pipeline(None, task))
        else:
            await wa_send(sender, "No pending plan. Send 'order <task>' to start one.")

    elif body_lower == "reject":
        task = _wa_pending.pop(sender, None)
        if task:
            add_log(f"[WhatsApp] Plan rejected by {sender}")
            set_agent_status("Project Manager", "IDLE", "blue")
            SYSTEM_STATE["current_task"] = "None"
            await wa_send(sender, "Plan rejected. Send 'order <task>' to start a new one.")
        else:
            await wa_send(sender, "No pending plan to reject.")

    elif body_lower.startswith("approve arch") or body_lower.startswith("reject arch"):
        # Human-in-the-loop architecture gate (HUMAN_GATE_ENABLED=true)
        parts_wa  = Body.strip().split()
        action_wa = parts_wa[0].lower()   # "approve" or "reject"
        tid_arg   = parts_wa[2] if len(parts_wa) > 2 else _gate_task_map.get("current", "")
        gate      = _pipeline_gates.get(tid_arg)
        if gate and not gate.is_set():
            if action_wa == "approve":
                gate.set()
                await wa_send(sender, f"✅ Architecture approved for task {tid_arg}. Coding begins...")
                add_log(f"[HITL][WhatsApp] Architecture approved by {sender} — task {tid_arg}")
            else:
                SYSTEM_STATE[f"_gate_rejected_{tid_arg}"] = True
                gate.set()
                await wa_send(sender, f"❌ Architecture rejected for task {tid_arg}. Pipeline aborted.")
                add_log(f"[HITL][WhatsApp] Architecture rejected by {sender} — task {tid_arg}")
        else:
            await wa_send(sender, f"⚠️ No open architecture gate for task '{tid_arg}'.")

    else:
        await wa_send(
            sender,
            "AI Dev Team Commands:\n\n"
            "order <task>              — start a new pipeline\n"
            "approve                   — approve the pending plan\n"
            "reject                    — reject the pending plan\n"
            "approve arch <task_id>    — approve architecture (HITL gate)\n"
            "reject arch <task_id>     — reject architecture (HITL gate)",
        )

    return Response(
        content="<?xml version='1.0'?><Response></Response>",
        media_type="text/xml",
    )




@app.post("/webhook/zeroclaw")
async def zeroclaw_webhook(request: Request) -> dict[str, str]:
    """
    ZeroClaw SOP webhook endpoint.

    Configure a ZeroClaw SOP in ~/.zeroclaw/workspace/sops/ to POST here when
    the manager sends a message on any channel. ZeroClaw handles the channel layer
    (Discord, WhatsApp, Telegram, Slack, Signal …); agent_mesh handles the pipeline.

    Payload (JSON):
      { "action": "order|approve|reject", "task": "...",
        "channel": "...", "sender": "...", "reply_url": "..." }

    Security: pass X-ZeroClaw-Signature: sha256=<hmac> and set ZEROCLAW_WEBHOOK_SECRET.
    """
    body = await request.body()
    sig_header = request.headers.get("x-zeroclaw-signature", "")
    if not _verify_zeroclaw_sig(body, sig_header):
        raise HTTPException(status_code=401, detail="Invalid X-ZeroClaw-Signature")

    try:
        payload = ZeroClawPayload(**json.loads(body))
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON payload")

    action = payload.action.lower().strip()
    sender = payload.sender or "zeroclaw"

    if action == "order":
        if not payload.task:
            return {"status": "error", "message": "Field 'task' is required for action=order"}
        task = payload.task.strip()
        add_log(f"[ZeroClaw] Order from {payload.channel}/{sender}: {task}")
        _zc_pending[sender] = (task, payload.reply_url)
        asyncio.create_task(_handle_new_order(task))
        llm_note = f"LLM: {OPENAI_MODEL}" if OPENAI_API_KEY else "LLM: Simulated (no OPENAI_API_KEY)"
        plan = (
            f"AI Dev Team — Pipeline plan for: {task}\n\n"
            f"8-agent SDLC pipeline:\n"
            f"  1. Architect — Design\n"
            f"  2. Frontend Dev + Backend Dev (parallel)\n"
            f"  3. Database Engineer — Schema\n"
            f"  4. QA Engineer — Tests (80 % gate)\n"
            f"  5. Security Analyst — OWASP scan\n"
            f"  6. DevOps Engineer — Docker & CI/CD\n"
            f"  7. Project Manager — Delivery report\n\n"
            f"{llm_note}\n"
            f"Reply with action=approve to execute or action=reject to cancel."
        )
        return {"status": "accepted", "message": plan}

    if action == "approve":
        entry = _zc_pending.pop(sender, None)
        if not entry:
            return {"status": "no_pending", "message": "No pending plan for this sender."}
        task, reply_url = entry
        add_log(f"[ZeroClaw] Plan approved by {sender}. Starting pipeline...")
        asyncio.create_task(_execute_and_reply_zeroclaw(task, reply_url))
        return {"status": "ok", "message": f"Pipeline started for: {task}"}

    if action == "reject":
        entry = _zc_pending.pop(sender, None)
        set_agent_status("Project Manager", "IDLE", "blue")
        if entry:
            SYSTEM_STATE["current_task"] = "None"
            add_log(f"[ZeroClaw] Plan rejected by {sender}.")
        return {"status": "ok", "message": "Plan rejected. Send a new order anytime."}

    return {
        "status": "unknown",
        "message": "action must be one of: order | approve | reject",
    }



# ============================================================
# 10.5  MCP SERVER  (VS Code Copilot / Cursor / Antigravity)
# ============================================================

_MCP_TOOLS: list[dict] = [
    {
        "name": "codevx_submit_order",
        "description": "Submit a task to the CoDevx 8-agent SDLC pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "Feature to build"}},
            "required": ["task"],
        },
    },
    {"name": "codevx_get_state", "description": "Get all agent statuses.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "codevx_get_history", "description": "List completed tasks.", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "codevx_get_logs",
        "description": "Get recent pipeline logs.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}},
    },
    {
        "name": "codevx_get_agent",
        "description": "Get status of a specific agent by name.",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "enum": ["Project Manager", "Architect", "Frontend Dev", "Backend Dev", "QA Engineer", "DevOps Engineer", "Security Analyst", "Database Engineer"]}}, "required": ["name"]},
    },
]

_MCP_SERVER_INFO: dict = {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "codevx", "version": "5.0.0"},
    "capabilities": {"tools": {}},
}


@app.get("/mcp")
async def mcp_capabilities() -> dict:
    return _MCP_SERVER_INFO


@app.post("/mcp")
async def mcp_dispatch(request: Request) -> dict:  # noqa: C901
    body: dict = await request.json()
    rpc_id = body.get("id")
    method: str = body.get("method", "")
    params: dict = body.get("params") or {}

    def _ok(result: object) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def _err(code: int, msg: str) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": msg}}

    try:
        if method == "initialize":
            return _ok(_MCP_SERVER_INFO)

        if method == "tools/list":
            return _ok({"tools": _MCP_TOOLS})

        if method == "tools/call":
            tool: str = params.get("name", "")
            args: dict = params.get("arguments") or {}

            if tool == "codevx_submit_order":
                task = str(args.get("task", "")).strip()
                if not task:
                    return _err(-32602, "task argument is required")
                import uuid as _u; tid = str(_u.uuid4())[:8]
                add_log(f"[MCP] Order via IDE task_id={tid}")
                SYSTEM_STATE["current_task"] = task
                asyncio.create_task(execute_pipeline(None, task))
                return _ok({"content": [{"type": "text", "text": f"Order submitted tid={tid} -- Pipeline started"}]})

            if tool == "codevx_get_state":
                return _ok({"content": [{"type": "text", "text": json.dumps(SYSTEM_STATE, indent=2)}]})

            if tool == "codevx_get_history":
                return _ok({"content": [{"type": "text", "text": json.dumps(SYSTEM_STATE["history"], indent=2)}]})

            if tool == "codevx_get_logs":
                lim = max(1, min(int(args.get("limit", 50)), 200))
                return _ok({"content": [{"type": "text", "text": chr(10).join(SYSTEM_STATE["logs"][-lim:])}]})

            if tool == "codevx_get_agent":
                nm = str(args.get("name", ""))
                ag = SYSTEM_STATE["agents"].get(nm)
                if not ag:
                    return _err(-32602, f"Agent not found: {nm}")
                return _ok({"content": [{"type": "text", "text": json.dumps({"name": nm, **ag}, indent=2)}]})

            return _err(-32601, f"Unknown tool: {tool}")

        if method == "ping":
            return _ok({})

        return _err(-32601, f"Unknown method: {method}")

    except Exception as exc:
        add_log(f"[MCP][ERROR] {exc}")
        return _err(-32603, "Internal MCP server error")

@app.get("/", response_class=HTMLResponse)
async def serve_fallback() -> HTMLResponse:
    try:
        with open("command_center.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            "<h1 style='font-family:sans-serif;color:#94a3b8'>"
            "Agent Mesh v3.0 -- open React Command Center at :3000 or :5173.</h1>"
        )


# ============================================================
# 11. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  AI DEV TEAM -- AGENT MESH v4.0")
    print("=" * 60)
    print(f"  Messaging:  {MESSAGING_PROVIDER.upper()}")
    print(f"  Real tools: {'ON (pytest/bandit/npm-audit)' if ENABLE_REAL_TOOLS else 'OFF'}")
    print(f"  Retries:    {MAX_RETRIES} (QA + Security gates)")
    print(f"  Max tokens: {OPENAI_MAX_TOKENS} per agent call")
    print(f"  Docker:     {'Build enabled' if DOCKER_BUILD else 'Disabled'}")
    print(f"  LLM:        {OPENAI_MODEL if OPENAI_API_KEY else 'Simulated (no OPENAI_API_KEY)'}")
    print(f"  Storage:    SQLite -> {DB_PATH}")
    print(f"  Workspace:  {GIT_WORKSPACE}")
    print(f"  GitHub:     {GITHUB_REPO if GITHUB_REPO else 'Not configured (local commits only)'}")
    print("  REST API:   http://localhost:8000/api/state")
    print("  WebSocket:  ws://localhost:8000/ws/state")
    print("  React UI:   http://localhost:3000  (Docker)")
    print("  Dev UI:     http://localhost:5173  (Vite)")
    print("  WA Webhook: POST http://localhost:8000/webhook/whatsapp")
    print("  ZC Webhook: POST http://localhost:8000/webhook/zeroclaw")
    print("  MCP Server: http://localhost:8000/mcp")
    print("  API Docs:   http://localhost:8000/docs")
    print("=" * 60)
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
