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

# LLM (OpenAI or any OpenAI-compatible endpoint)
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")  # blank = official OpenAI

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
MAX_RETRIES       = int(os.getenv("MAX_RETRIES", "2"))             # QA / Security retry attempts
MAX_SUBTASKS      = int(os.getenv("MAX_SUBTASKS", "5"))            # max implementation phases
ENABLE_REAL_TOOLS = os.getenv("ENABLE_REAL_TOOLS", "true").lower() == "true"  # run pytest/bandit/npm-audit
DOCKER_BUILD      = os.getenv("DOCKER_BUILD", "false").lower() == "true"      # docker build after pipeline
MEMORY_CONTEXT_K  = int(os.getenv("MEMORY_CONTEXT_K", "5"))       # past memories to inject

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
        "You are a principal software architect with expertise in distributed systems, "
        "microservices, SaaS platforms, multi-tenant architecture, and AI system design.\n\n"
        "Given a feature request, produce a structured architecture document:\n"
        "1. **Overview** — What is being built and why (3-5 sentences)\n"
        "2. **Files to create** — Full relative path + purpose for each file\n"
        "3. **API contracts** — Method, path, request/response shapes (JSON)\n"
        "4. **Data models** — Key entities, fields, types, relationships\n"
        "5. **New dependencies** — pip or npm packages required\n"
        "6. **Security design** — Auth strategy, input validation points, data exposure risks\n"
        "7. **Scalability** — Caching, queuing, indexes, sharding if relevant\n\n"
        "Be precise and technical. No filler text. No vague statements."
    ),
    "Frontend Dev": (
        "You are a senior React 19 / TypeScript / Tailwind CSS engineer building production UIs.\n\n"
        "For EACH file you produce, begin with the exact marker line:\n"
        "  // FILE: relative/path/to/component.tsx\n"
        "Then write the COMPLETE file content immediately after — no truncation, no placeholders.\n\n"
        "Standards:\n"
        "- Named exports only (never default export)\n"
        "- Strict TypeScript — no `any`, no implicit types, interfaces over type aliases for objects\n"
        "- Tailwind CSS dark-mode slate palette\n"
        "- Accessible: aria-label on all interactive elements, semantic HTML5\n"
        "- React Query (TanStack) for server state, Zustand for client state\n"
        "- Zod schemas for all form validation\n"
        "- Error boundary + Suspense wrappers for every async component\n"
        "- Loading skeletons, empty states, and error states required\n"
        "- No TODO comments, no placeholder logic, no stub implementations"
    ),
    "Backend Dev": (
        "You are a senior FastAPI / Python 3.12 engineer building production-grade APIs.\n\n"
        "For EACH file, begin with the exact marker line:\n"
        "  # FILE: relative/path/to/module.py\n"
        "Then write the COMPLETE file content immediately after — no truncation.\n\n"
        "Standards:\n"
        "- Full PEP 695 type hints on every function, class, and variable\n"
        "- Pydantic v2 models for all request/response schemas\n"
        "- NEVER raw string formatting for SQL — parameterized queries only\n"
        "- JWT auth via `python-jose` or `authlib` when auth is required\n"
        "- Rate limiting via `slowapi` on all public endpoints\n"
        "- `httpx.AsyncClient` for any outbound HTTP (never `requests`)\n"
        "- Structured logging with `structlog` — never print() in production code\n"
        "- Never expose internal stack traces to API clients (use HTTPException)\n"
        "- Repository pattern to decouple business logic from persistence\n"
        "- Input validation on ALL user-supplied data — assume hostile input"
    ),
    "Database Engineer": (
        "You are a database architect expert in PostgreSQL, SQLite, Redis, and TimescaleDB.\n\n"
        "For EACH file, begin with:\n"
        "  -- FILE: migrations/NNNN_description.sql\n"
        "Then write the COMPLETE SQL immediately after.\n\n"
        "Standards:\n"
        "- All DDL is idempotent: IF NOT EXISTS, CREATE OR REPLACE\n"
        "- Every table has: id (UUID or BIGSERIAL), created_at, updated_at\n"
        "- Soft deletes: deleted_at TIMESTAMPTZ nullable (never hard-delete user data)\n"
        "- Indexes on every foreign key and every column used in WHERE/ORDER BY\n"
        "- CHECK constraints for enum-like columns\n"
        "- Row-level security (RLS) policies for multi-tenant schemas\n"
        "- Composite unique indexes for natural keys\n"
        "- Comments on every table and non-obvious column\n"
        "Write complete, production-safe migrations that can run on a live database."
    ),
    "QA Engineer": (
        "You are a senior QA engineer specializing in pytest, Vitest, and integration testing.\n\n"
        "For EACH test file, begin with:\n"
        "  # FILE: tests/test_feature_name.py\n"
        "Then write the COMPLETE test code.\n\n"
        "Standards:\n"
        "- Target >= 85% branch coverage on all new code paths\n"
        "- Required per feature: unit tests + at least one integration test\n"
        "- pytest fixtures in conftest.py for DB setup, HTTP client, auth tokens\n"
        "- Mock ALL external services: httpx, SMTP, S3, third-party APIs\n"
        "- Never call real external APIs or write to production DB in tests\n"
        "- Test happy path, validation failures, auth failures, edge cases, concurrency\n"
        "- `pytest-asyncio` for all async endpoints\n"
        "- Use `httpx.AsyncClient` + ASGI transport for FastAPI integration tests\n"
        "- For TypeScript: Vitest + Testing Library + MSW for API mocking\n"
        "Write tests that ACTUALLY RUN and PASS against the implementation provided."
    ),
    "Security Analyst": (
        "You are an AppSec engineer. Review all provided code against the OWASP Top 10.\n\n"
        "Output format (REQUIRED — do not deviate):\n\n"
        "## Findings\n"
        "For each issue:\n"
        "  SEVERITY: CRITICAL | HIGH | MEDIUM | LOW\n"
        "  Location: filename:line (if identifiable)\n"
        "  Issue: brief description\n"
        "  Fix: exact code change or config required\n\n"
        "## Patches\n"
        "For every CRITICAL or HIGH finding, output the COMPLETE fixed file:\n"
        "  # FILE: path/to/fixed_file.py\n"
        "  <full corrected file content>\n\n"
        "## Verdict\n"
        "End with EXACTLY one of:\n"
        "  SCAN: PASSED\n"
        "  SCAN: FAILED\n\n"
        "Fail if ANY of these exist unmitigated:\n"
        "SQL injection, XSS, hardcoded secrets, missing auth/authz, insecure deserialization,\n"
        "SSRF, path traversal, broken access control, mass assignment, unvalidated redirects,\n"
        "missing rate limiting on auth endpoints, JWT algorithm confusion."
    ),
    "DevOps Engineer": (
        "You are a senior DevOps engineer specializing in Docker, GitHub Actions, and cloud-native deployment.\n\n"
        "For EACH config file, begin with the marker:\n"
        "  # FILE: .github/workflows/ci.yml\n"
        "Then write the COMPLETE file.\n\n"
        "Always produce ALL of:\n"
        "1. Dockerfile (multi-stage build, non-root USER, minimal base image)\n"
        "2. docker-compose.yml (local dev stack with all service dependencies)\n"
        "3. .github/workflows/ci.yml (lint -> test -> security scan -> build -> optional deploy)\n"
        "4. .dockerignore\n"
        "5. Makefile or Justfile with: make dev, make test, make build, make deploy\n\n"
        "Standards:\n"
        "- Pin ALL image versions (never :latest)\n"
        "- Health checks on every service\n"
        "- Secrets via environment variables only — never baked into images\n"
        "- CI: fail fast (lint before build, test before deploy)\n"
        "- Resource limits (memory/cpu) on all services in compose\n"
        "- Read-only filesystem where possible\n"
        "Write complete, deployable configurations that work as-is."
    ),
    "Project Manager": (
        "You are an AI project manager writing a stakeholder delivery report.\n\n"
        "Structure your report exactly as:\n\n"
        "## Delivered\n"
        "Concise bullet list of what was built.\n\n"
        "## Quality Gate\n"
        "- Test coverage: X%\n"
        "- Security scan: PASSED | FAILED\n"
        "- Known gaps or tech debt\n\n"
        "## Deployment Status\n"
        "- Branch: feat/xxxx\n"
        "- PR: <url or 'not created'>\n"
        "- Files generated: N\n"
        "- Docker build: OK | FAILED | SKIPPED\n\n"
        "## Risks & Next Steps\n"
        "- What is NOT yet done\n"
        "- Recommended follow-up orders\n\n"
        "Keep under 500 words. Professional, direct, no filler."
    ),
}



async def llm_call(agent: str, user_message: str) -> str:
    """Call the configured LLM for the given agent. Falls back to simulation if no key."""
    if not OPENAI_API_KEY:
        add_log(f"[{agent}] Simulating (set OPENAI_API_KEY for real LLM).")
        await asyncio.sleep(1)
        slug = agent.lower().replace(" ", "_")
        return (
            f"[SIMULATED — no OPENAI_API_KEY]\n"
            f"# FILE: workspace/{slug}/main.py\n"
            f"# {agent} placeholder for: {user_message[:120]}\n"
            f"def placeholder(): pass  # replace with real LLM output\n"
        )
    try:
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        client = AsyncOpenAI(**kwargs)
        add_log(f"[{agent}] Calling {OPENAI_MODEL}...")
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPTS.get(agent, "You are a helpful AI.")},
                {"role": "user",   "content": user_message},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        add_log(f"[{agent}] LLM error: {exc}")
        return f"[LLM ERROR] {exc}"


def parse_files_from_llm(output: str) -> list[dict]:
    """Extract FILE: path blocks from LLM output."""
    pattern = re.compile(
        r"(?://|#|--)\s+FILE:\s+(.+?)\n(.*?)(?=(?://|#|--)\s+FILE:|\Z)",
        re.DOTALL,
    )
    return [
        {"path": m.group(1).strip(), "content": m.group(2).strip()}
        for m in pattern.finditer(output)
    ]



# ============================================================
# 5.5  AGENT MEMORY  (cross-task learning stored in SQLite)
# ============================================================

async def memory_store(task_id: str, agent: str, category: str, content: str) -> None:
    """Persist a key agent insight for injection into future pipeline runs."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO agent_memory (task_id, agent, category, content) VALUES (?,?,?,?)",
                (task_id, agent, category, content[:600]),
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
# 9. EXECUTION PIPELINE
# ============================================================

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
        ctx["arch"] = arch_out
        add_log(f"[Architect] {arch_out.splitlines()[0][:120]}")
        add_log("[Architect] Architecture complete.")
        set_agent_status("Architect", "IDLE", "purple")

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
                "Previously written BE:\n" + be_prev
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
            set_agent_status("Database Engineer", "IDLE", "gray")

        # QA GATE — test all generated files + retry loop
        for qa_attempt in range(MAX_RETRIES + 1):
            set_agent_status("QA Engineer", "TESTING...", "yellow")
            retry_lbl = f" (retry {qa_attempt}/{MAX_RETRIES})" if qa_attempt else ""
            add_log(f"[QA Engineer] Writing test suites{retry_lbl}...")

            qa_ctx = (
                "Task: " + task + "\n\n"
                "Architecture:\n" + arch_out[:700] + "\n\n"
                "Frontend code:\n" + fe_out[:1200] + "\n\n"
                "Backend code:\n" + be_out[:1200]
            )
            if qa_attempt > 0 and ctx.get("test_output"):
                qa_ctx += "\n\nTest failures to fix:\n" + ctx["test_output"][:600]

            qa_out  = await llm_call("QA Engineer", qa_ctx)
            ctx["qa"] = qa_out
            qa_new  = parse_files_from_llm(qa_out)
            qa_files.extend(qa_new)
            all_files.extend(qa_new)
            _write_files_to_workspace(qa_new)

            if ENABLE_REAL_TOOLS:
                test_res            = await run_tests_real(GIT_WORKSPACE)
                ctx["test_output"]  = test_res["output"]
                coverage            = test_res.get("coverage", 0)
                status              = "PASSED" if test_res["passed"] else "FAILED"
                add_log(f"[QA Engineer] Real tests: {status} | Coverage: {coverage}%")
                if test_res["passed"] and coverage >= 80:
                    break
                if qa_attempt >= MAX_RETRIES:
                    add_log("[QA Engineer] Max retries reached — proceeding with best effort.")
                    break
            else:
                add_log(f"[QA Engineer] {len(qa_new)} test file(s) written. (ENABLE_REAL_TOOLS=false)")
                break

        set_agent_status("QA Engineer", "IDLE", "yellow")

        # SECURITY GATE — full codebase review + tool scan + fix loop
        for sec_attempt in range(MAX_RETRIES + 1):
            set_agent_status("Security Analyst", "SCANNING...", "red")
            retry_lbl = f" (retry {sec_attempt}/{MAX_RETRIES})" if sec_attempt else ""
            add_log(f"[Security Analyst] OWASP Top 10 review{retry_lbl}...")

            sec_ctx = (
                "Review for OWASP Top 10:\n\n"
                "Frontend:\n" + fe_out[:1000] + "\n\n"
                "Backend:\n" + be_out[:1000]
            )
            if sec_attempt > 0 and ctx.get("scan_output"):
                sec_ctx += "\n\nPrevious scan findings:\n" + ctx["scan_output"][:500]

            sec_out     = await llm_call("Security Analyst", sec_ctx)
            ctx["security"] = sec_out
            scan_passed = "SCAN: FAILED" not in sec_out.upper()

            # Real bandit + npm audit
            if ENABLE_REAL_TOOLS:
                real_scan          = await run_security_real(GIT_WORKSPACE)
                ctx["scan_output"] = real_scan["output"]
                add_log(
                    f"[Security Analyst] bandit: {real_scan['python_issues']} | "
                    f"npm audit: {real_scan['npm_issues']}"
                )

            add_log(f"[Security Analyst] LLM verdict: {'PASSED' if scan_passed else 'FAILED'}")
            if scan_passed:
                break

            if sec_attempt >= MAX_RETRIES:
                raise RuntimeError(
                    "Security scan FAILED after all retry attempts — "
                    "unresolved CRITICAL/HIGH vulnerabilities detected."
                )

            # Apply security fix files from LLM output, then retry
            fix_files = parse_files_from_llm(sec_out)
            if fix_files:
                all_files.extend(fix_files)
                _write_files_to_workspace(fix_files)
                add_log(f"[Security Analyst] {len(fix_files)} fix file(s) applied — retrying scan.")
                be_out += "\n" + sec_out   # update context for next attempt

        set_agent_status("Security Analyst", "IDLE", "red")

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
        await memory_store(task_id, "Architect",        "architecture", arch_out[:500])
        await memory_store(task_id, "Backend Dev",      "patterns",     be_out[:400])
        await memory_store(task_id, "Security Analyst", "findings",     ctx.get("security", "")[:400])
        await memory_store(task_id, "Project Manager",  "delivery",     pm_out[:400])

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


app = FastAPI(title="AI Dev Team -- Agent Mesh", version="3.0.0", lifespan=lifespan)

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

    else:
        await wa_send(
            sender,
            "AI Dev Team Commands:\n\n"
            "order <task> -- start a new pipeline\n"
            "approve -- approve the pending plan\n"
            "reject -- reject the pending plan",
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
    print("  API Docs:   http://localhost:8000/docs")
    print("=" * 60)
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
