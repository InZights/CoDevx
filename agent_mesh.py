"""
CoDevx — Agent Mesh v4.0
================================
Autonomous 8-agent AI software development team.
FastAPI backend with:
  - AgentScope-powered pipeline with MsgHub collaboration + self-correcting loops
  - LiteLLM-powered fallback pipeline (100+ LLM providers)
  - SQLite persistence (aiosqlite) — logs, tasks, files, memory
  - AgentScope ListMemory (in-context) + SQLite (cross-session) dual memory
  - Git workspace — auto-branch, commit, GitHub PR
  - Tool execution — pytest, bandit, npm audit (via AgentScope ServiceToolkit)
  - Discord bot bridge (4-channel) + WhatsApp/Twilio + ZeroClaw webhooks
  - WebSocket real-time state push  (/ws/state)
  - REST /api/* + POST /api/order  (browser-accessible)
  - MCP server (/mcp)  — VS Code Copilot · Cursor · Antigravity
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite
import discord
import uvicorn
from discord.ext import commands
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

# ── AgentScope integration (optional — graceful degradation if not installed) ──
try:
    from agentscope_init import init_agentscope, AgentScopeConfig  # type: ignore[import]
    _AGENTSCOPE_IMPORTABLE = True
except ImportError:
    _AGENTSCOPE_IMPORTABLE = False

    class AgentScopeConfig:  # type: ignore[no-redef]
        enabled = False

try:
    from agentscope_pipeline import execute_agentscope_pipeline  # type: ignore[import]
    _AS_PIPELINE_IMPORTABLE = True
except ImportError:
    _AS_PIPELINE_IMPORTABLE = False

# ============================================================
# 1. CONFIGURATION
# ============================================================

# ── Discord ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN", "")
MANAGER_DISCORD_ID = int(os.getenv("MANAGER_DISCORD_ID", "0"))
CH_ORDERS   = int(os.getenv("DISCORD_CHANNEL_ORDERS",   "0"))
CH_PLANS    = int(os.getenv("DISCORD_CHANNEL_PLANS",    "0"))
CH_ACTIVITY = int(os.getenv("DISCORD_CHANNEL_ACTIVITY", "0"))
CH_REPORTS  = int(os.getenv("DISCORD_CHANNEL_REPORTS",  "0"))

# ── CORS ───────────────────────────────────────────────────────────────────────
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_MODEL         = os.getenv("LLM_MODEL", "gpt-4o")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
LLM_ENABLED       = bool(OPENAI_API_KEY)

# ── Pipeline controls ──────────────────────────────────────────────────────────
MAX_RETRIES         = int(os.getenv("MAX_RETRIES", "2"))
MAX_SUBTASKS        = int(os.getenv("MAX_SUBTASKS", "5"))
MEMORY_CONTEXT_K    = int(os.getenv("MEMORY_CONTEXT_K", "5"))
ENABLE_REAL_TOOLS   = os.getenv("ENABLE_REAL_TOOLS", "false").lower() == "true"
DOCKER_BUILD        = os.getenv("DOCKER_BUILD",        "false").lower() == "true"

# ── AgentScope controls ────────────────────────────────────────────────────────
AGENTSCOPE_ENABLED  = os.getenv("AGENTSCOPE_ENABLED", "true").lower() not in {"false", "0", "no"}
MSGHUB_ROUNDS       = int(os.getenv("MSGHUB_ROUNDS", "2"))

# ── Storage ────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "./agent_mesh.db")

# ── Git / GitHub ───────────────────────────────────────────────────────────────
GIT_WORKSPACE = os.getenv("GIT_WORKSPACE", "./workspace")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO   = os.getenv("GITHUB_REPO", "")

# ── WhatsApp / Twilio ──────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN_ = os.getenv("TWILIO_AUTH_TOKEN", "")   # trailing _ avoids name clash
TWILIO_FROM        = os.getenv("TWILIO_WHATSAPP_FROM", "")
MANAGER_WHATSAPP   = os.getenv("MANAGER_WHATSAPP", "")

# ── ZeroClaw ──────────────────────────────────────────────────────────────────
ZEROCLAW_URL    = os.getenv("ZEROCLAW_GATEWAY_URL", "http://localhost:42617")
ZEROCLAW_SECRET = os.getenv("ZEROCLAW_WEBHOOK_SECRET", "")
MESSAGING_PROVIDER = os.getenv("MESSAGING_PROVIDER", "discord")


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
    "logs": ["[BOOT] CoDevx Agent Mesh v4.0 initializing (AgentScope edition)..."],
    "history": [],
    "llm_enabled":        LLM_ENABLED,
    "git_enabled":        bool(GITHUB_TOKEN),
    "real_tools_enabled": ENABLE_REAL_TOOLS,
    "zeroclaw_enabled":   MESSAGING_PROVIDER == "zeroclaw",
    "messaging":          MESSAGING_PROVIDER,
    "agentscope_enabled": False,   # updated after init_agentscope() runs in lifespan
    "agentscope_config":  None,    # populated with AgentScopeConfig after init
}

_ws_clients: set[WebSocket] = set()
_db: aiosqlite.Connection | None = None


# ============================================================
# 3. DATABASE  (aiosqlite)
# ============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT    NOT NULL,
    message TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS task_history (
    id             TEXT    PRIMARY KEY,
    description    TEXT    NOT NULL,
    completed_at   TEXT    NOT NULL,
    files_modified INTEGER DEFAULT 0,
    tests_passed   INTEGER DEFAULT 0,
    branch         TEXT,
    pr_url         TEXT,
    llm_used       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS generated_files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT    NOT NULL,
    file_path  TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_memory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT    NOT NULL,
    agent        TEXT    NOT NULL,
    memory_type  TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);
"""


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(_SCHEMA)
    await _db.commit()
    # Pre-load task history into SYSTEM_STATE
    rows = await db_load_history()
    if rows:
        SYSTEM_STATE["history"] = rows


async def db_log(ts: str, message: str) -> None:
    if not _db:
        return
    await _db.execute("INSERT INTO logs (ts, message) VALUES (?, ?)", (ts, message))
    await _db.commit()
    await _db.execute(
        "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 100)"
    )
    await _db.commit()


async def db_save_task(record: dict[str, Any]) -> None:
    if not _db:
        return
    await _db.execute(
        """INSERT INTO task_history
           (id, description, completed_at, files_modified, tests_passed, branch, pr_url, llm_used)
           VALUES (:id, :description, :completed_at, :files_modified, :tests_passed, :branch, :pr_url, :llm_used)
           ON CONFLICT(id) DO UPDATE SET
             files_modified = excluded.files_modified,
             tests_passed   = excluded.tests_passed,
             branch         = excluded.branch,
             pr_url         = excluded.pr_url,
             llm_used       = excluded.llm_used
        """,
        record,
    )
    await _db.commit()


async def db_save_file(task_id: str, rel_path: str, content: str) -> None:
    if not _db:
        return
    await _db.execute(
        "INSERT INTO generated_files (task_id, file_path, content, created_at) VALUES (?, ?, ?, ?)",
        (task_id, rel_path, content, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    await _db.commit()


async def db_store_memory(task_id: str, agent: str, memory_type: str, content: str) -> None:
    if not _db:
        return
    await _db.execute(
        "INSERT INTO agent_memory (task_id, agent, memory_type, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, agent, memory_type, content, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    await _db.commit()


async def db_recall_memories(agent: str, k: int = 5) -> list[str]:
    if not _db:
        return []
    async with _db.execute(
        "SELECT content FROM agent_memory WHERE agent = ? ORDER BY id DESC LIMIT ?",
        (agent, k),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in reversed(rows)]


async def db_load_history() -> list[dict[str, Any]]:
    if not _db:
        return []
    async with _db.execute(
        "SELECT * FROM task_history ORDER BY completed_at DESC LIMIT 50"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def db_get_files(task_id: str) -> list[dict[str, Any]]:
    if not _db:
        return []
    async with _db.execute(
        "SELECT file_path, content, created_at FROM generated_files WHERE task_id = ?",
        (task_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


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
    asyncio.create_task(_post_to_channel(CH_ACTIVITY, entry))
    asyncio.create_task(db_log(ts, entry))


def set_agent_status(name: str, status: str, color: str) -> None:
    if name in SYSTEM_STATE["agents"]:
        SYSTEM_STATE["agents"][name] = {"status": status, "color": color}
    asyncio.create_task(_broadcast())


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


async def _post_to_channel(channel_id: int, message: str) -> None:
    if not channel_id or not bot.is_ready():
        return
    ch = bot.get_channel(channel_id)
    if ch:
        try:
            await ch.send(message[:2000])
        except discord.HTTPException:
            pass


# ============================================================
# 5. LLM CALLER
# ============================================================

_BASE_OUTPUT_FORMAT = """
Respond with a single valid JSON object with exactly these keys:
{
  "summary": "<concise description of what you did>",
  "files": [
    {"path": "<relative path from workspace root>", "content": "<full file content>"},
    ...
  ],
  "notes": ["<important decision or finding for team memory>", ...]
}
Output raw JSON only — no markdown fences, no preamble.
"""


async def call_llm(
    agent_name: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.4,
) -> str:
    """Call LiteLLM with the configured model. Gracefully falls back to simulation."""
    if not LLM_ENABLED:
        await asyncio.sleep(1)
        return json.dumps({
            "summary": f"[SIMULATION] {agent_name} — set OPENAI_API_KEY for real LLM output.",
            "files": [],
            "notes": [f"{agent_name} ran in simulation mode."],
        })
    try:
        import litellm  # lazy import — only when API key present
        response = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        add_log(f"[LLM][ERROR] {agent_name}: {exc}")
        raise


def _parse_agent_response(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text, "files": [], "notes": []}


# ============================================================
# 5.1  FILE & GIT UTILITIES
# ============================================================

async def write_workspace_file(task_id: str, rel_path: str, content: str) -> None:
    """Write a generated file to the workspace dir and persist to DB."""
    abs_path = os.path.join(GIT_WORKSPACE, rel_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    await db_save_file(task_id, rel_path, content)
    add_log(f"[FILE] ✍  {rel_path}")


def _read_project_architecture() -> str:
    """Read the living project architecture document from the workspace (if it exists)."""
    arch_path = os.path.join(GIT_WORKSPACE, "docs", "PROJECT_ARCHITECTURE.md")
    if os.path.exists(arch_path):
        with open(arch_path, encoding="utf-8") as fh:
            return fh.read()
    return ""


async def _run_subprocess(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a subprocess without shell=True. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode or 0,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


# ── Infrastructure file detection ─────────────────────────────────────────────
# Files matching these patterns require a dedicated human review gate because
# they can affect live infrastructure, cloud spend, or security posture.
_INFRA_PATTERNS: tuple[str, ...] = (
    ".github/workflows/",
    "k8s/",
    "terraform/",
    "cdk/",
    "Dockerfile",
    "docker-compose",
    "helmfile",
    "charts/",
    "monitoring/",
)


def _detect_infra_files(file_paths: list[str]) -> list[str]:
    """Return any paths that match infrastructure patterns (case-insensitive)."""
    return [
        p for p in file_paths
        if any(pat.lower() in p.lower() for pat in _INFRA_PATTERNS)
    ]


async def git_init_workspace() -> None:
    """Ensure GIT_WORKSPACE exists and contains an initialised git repo."""
    os.makedirs(GIT_WORKSPACE, exist_ok=True)
    if not os.path.isdir(os.path.join(GIT_WORKSPACE, ".git")):
        await _run_subprocess(["git", "init"], cwd=GIT_WORKSPACE)
        await _run_subprocess(["git", "checkout", "-b", "main"], cwd=GIT_WORKSPACE)
        add_log(f"[GIT] Initialised repo at {GIT_WORKSPACE}")


async def git_commit_push(
    task_id: str,
    branch: str,
    file_paths: list[str] | None = None,
) -> str | None:
    """Create a branch, commit all staged files, push, and optionally open a PR.

    Args:
        task_id:    Short task UUID used for commit message and PR title.
        branch:     Feature branch name (e.g. 'feat/abc123').
        file_paths: Relative paths of all generated files — used to detect
                    infrastructure files and trigger the infra review gate.
    """
    ws = GIT_WORKSPACE
    if not os.path.isdir(os.path.join(ws, ".git")):
        return None
    for cmd in [
        ["git", "-C", ws, "checkout", "-b", branch],
        ["git", "-C", ws, "add", "."],
        ["git", "-C", ws, "commit", "-m", f"feat: {task_id} — CoDevx automated delivery"],
    ]:
        rc, out, err = await _run_subprocess(cmd)
        if rc != 0:
            add_log(f"[GIT][WARN] {' '.join(cmd[-2:])}: {(err or out)[:200]}")

    infra_files = _detect_infra_files(file_paths or [])
    if infra_files:
        add_log(
            f"[GIT][INFRA GATE] ⚠️  {len(infra_files)} infra file(s) detected — "
            "PR will require dedicated infrastructure review before merge."
        )

    pr_url: str | None = None
    if GITHUB_TOKEN and GITHUB_REPO:
        remote = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        rc, _, err = await _run_subprocess(["git", "-C", ws, "push", "-u", remote, branch])
        if rc != 0:
            add_log(f"[GIT][WARN] push failed: {err[:200]}")
        else:
            pr_url = await _create_github_pr(branch, task_id, infra_files, file_paths or [])
    return pr_url


async def _create_github_pr(
    branch: str,
    task_id: str,
    infra_files: list[str],
    all_file_paths: list[str],
) -> str | None:
    """Open a pull request via the GitHub REST API.

    When infrastructure files are present the PR body contains a mandatory
    review checklist and the 'infra-review' label is applied so branch
    protection rules can require a specialist review before merging.
    """
    app_files = [p for p in all_file_paths if p not in infra_files]

    # ── Build PR body ────────────────────────────────────────────────────────
    infra_section = ""
    if infra_files:
        checklist = "\n".join(f"- [ ] `{p}`" for p in infra_files)
        infra_section = (
            "\n---\n"
            "## ⚠️  INFRASTRUCTURE FILES — MANDATORY REVIEW BEFORE MERGE\n\n"
            "This PR contains files that affect live infrastructure, cloud spend, "
            "or security posture. **Do NOT merge without completing this checklist:**\n\n"
            "- [ ] Reviewed all `.github/workflows/` files for unintended deploy triggers\n"
            "- [ ] Verified CI/CD environment targets are correct (staging ≠ production)\n"
            "- [ ] Confirmed no AWS/cloud credentials are hardcoded in workflows\n"
            "- [ ] Checked `Dockerfile` / `k8s/` for security misconfigurations\n"
            "- [ ] All deploy jobs confirmed as `workflow_dispatch` (manual trigger)\n"
            "- [ ] Ran `terraform plan` locally before merging (if IaC files present)\n\n"
            f"**Infrastructure files in this PR ({len(infra_files)}):**\n{checklist}\n"
        )

    app_section = ""
    if app_files:
        app_list = "\n".join(f"- `{p}`" for p in app_files[:30])
        if len(app_files) > 30:
            app_list += f"\n- … and {len(app_files) - 30} more"
        app_section = f"\n---\n## 📦 Application Files ({len(app_files)})\n\n{app_list}\n"

    body = (
        f"## 🤖 CoDevx Automated Delivery — Task `{task_id}`\n\n"
        f"Generated by the **CoDevx 8-agent SDLC pipeline** (Agent Mesh v3.0).\n"
        + infra_section
        + app_section
        + "\n---\n"
        + ("\n> 🔒 **Reminder:** Infra files require dedicated review — see checklist above.\n"
           if infra_files else
           "\n> ✅ No infrastructure files detected. Standard code review applies.\n")
    )

    labels = ["codevx-delivery"] + (["infra-review"] if infra_files else [])

    try:
        import httpx
        gh_headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Create the PR
            resp = await client.post(
                f"https://api.github.com/repos/{GITHUB_REPO}/pulls",
                headers=gh_headers,
                json={
                    "title": (
                        ("[INFRA REVIEW] " if infra_files else "")
                        + f"feat: CoDevx delivery — task {task_id}"
                    ),
                    "body": body,
                    "head": branch,
                    "base": "main",
                },
            )
            if resp.status_code != 201:
                add_log(f"[GIT][WARN] PR status {resp.status_code}: {resp.text[:200]}")
                return None

            pr_data = resp.json()
            pr_number: int = pr_data["number"]
            url: str = pr_data.get("html_url", "")

            # Ensure labels exist then apply them
            for label_name in labels:
                color = "e11d48" if label_name == "infra-review" else "6366f1"
                await client.post(
                    f"https://api.github.com/repos/{GITHUB_REPO}/labels",
                    headers=gh_headers,
                    json={"name": label_name, "color": color},
                )  # 422 = already exists, safe to ignore
            await client.post(
                f"https://api.github.com/repos/{GITHUB_REPO}/issues/{pr_number}/labels",
                headers=gh_headers,
                json={"labels": labels},
            )

        add_log(
            f"[GIT] ✅ PR #{pr_number} opened: {url}"
            + (" | 🔴 infra-review label applied" if infra_files else "")
        )
        return url
    except Exception as exc:
        add_log(f"[GIT][PR][ERROR] {exc}")
    return None


# ============================================================
# 5.2  TOOL EXECUTION
# ============================================================

async def run_pytest(cwd: str) -> tuple[bool, str, int]:
    """Run pytest. Returns (passed, output, test_count)."""
    if not ENABLE_REAL_TOOLS:
        return True, "pytest skipped (ENABLE_REAL_TOOLS=false)", 0
    rc, out, err = await _run_subprocess(
        ["python", "-m", "pytest", "--tb=short", "-q",
         "--cov=.", "--cov-report=term-missing"],
        cwd=cwd,
    )
    combined = out + err
    match = re.search(r"(\d+) passed", combined)
    count = int(match.group(1)) if match else 0
    return rc == 0, combined[:3000], count


async def run_bandit(cwd: str) -> tuple[bool, str]:
    """Run bandit SAST scan. Returns (clean, output)."""
    if not ENABLE_REAL_TOOLS:
        return True, "bandit skipped (ENABLE_REAL_TOOLS=false)"
    rc, out, err = await _run_subprocess(
        ["python", "-m", "bandit", "-r", ".", "-ll", "-f", "txt", "--exit-zero"],
        cwd=cwd,
    )
    combined = out + err
    has_high = "Severity: High" in combined or "Severity: Critical" in combined
    return not has_high, combined[:3000]


async def run_npm_audit(cwd: str) -> tuple[bool, str]:
    """Run npm audit. Returns (clean, output)."""
    if not ENABLE_REAL_TOOLS:
        return True, "npm audit skipped (ENABLE_REAL_TOOLS=false)"
    rc, out, err = await _run_subprocess(["npm", "audit", "--audit-level=high"], cwd=cwd)
    return rc == 0, (out + err)[:3000]


# ============================================================
# 6. AGENT SYSTEM PROMPTS
# ============================================================

AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "Project Manager": (
        "You are the Project Manager of CoDevx, an autonomous AI software development team.\n"
        "Your role: decompose tasks, assign phases, write delivery reports, store learnings.\n"
        "When writing a delivery report: summarise what was built, highlight risks, and note\n"
        "one key learning per agent in your notes array.\n"
    ) + _BASE_OUTPUT_FORMAT,

    "Architect": (
        "You are the Architect of CoDevx. Design the complete technical solution before code is written.\n"
        "For every task produce:\n"
        "1. API endpoints (method, path, request/response shape)\n"
        "2. Data models (fields, types, relationships)\n"
        "3. React component tree (component names, props)\n"
        "4. Technology decisions with trade-off justification\n"
        "5. Auth & security design (OWASP considerations)\n"
        "Write a design document as docs/architecture_<slug>.md.\n"
        "Be specific — developer agents implement EXACTLY what you specify.\n"
    ) + _BASE_OUTPUT_FORMAT,

    "Frontend Dev": (
        "You are the Frontend Developer of CoDevx.\n"
        "Stack: React 18+, TypeScript (strict), Tailwind CSS, shadcn/ui, React Query v5, Zod.\n"
        "Rules:\n"
        "- Named exports only (no default exports)\n"
        "- No `any` type — use proper generics and type narrowing\n"
        "- All forms validated with Zod schemas\n"
        "- WCAG 2.1 AA accessible\n"
        "- Mobile-first responsive design\n"
        "- Components in src/components/, pages in src/pages/, types in src/types/\n"
        "- Include loading and error states in every component\n"
    ) + _BASE_OUTPUT_FORMAT,

    "Backend Dev": (
        "You are the Backend Developer of CoDevx.\n"
        "Stack: FastAPI, Python 3.12, async SQLAlchemy 2.0, Pydantic v2, structlog.\n"
        "Rules:\n"
        "- Full type hints on every function signature\n"
        "- Input validated with Pydantic v2 models (no raw dict access)\n"
        "- Async/await throughout — never blocking calls in async context\n"
        "- Parameterised queries only — never f-string SQL\n"
        "- HTTPException with safe messages — never expose raw exceptions to clients\n"
        "- structlog for logging — never print() in production\n"
        "- Rate-limit auth endpoints\n"
        "Structure: src/routes/, src/services/, src/schemas/, src/models/\n"
    ) + _BASE_OUTPUT_FORMAT,

    "Database Engineer": (
        "You are the Database Engineer of CoDevx.\n"
        "Stack: PostgreSQL, Alembic, Redis (caching), aiosqlite (embedded).\n"
        "Rules:\n"
        "- Declarative SQLAlchemy Base models\n"
        "- BIGSERIAL / BIGINT primary keys\n"
        "- updated_at triggers on all mutable tables\n"
        "- Never raw string formatting for SQL\n"
        "- All migrations reversible (upgrade + downgrade)\n"
        "- Index FKs and frequently queried columns\n"
        "Output: alembic/versions/*.py, sql/schema.sql, sql/rls.sql\n"
    ) + _BASE_OUTPUT_FORMAT,

    "QA Engineer": (
        "You are the QA Engineer of CoDevx.\n"
        "Stack: pytest, hypothesis, Vitest, httpx.AsyncClient.\n"
        "Rules:\n"
        "- Target ≥85% branch coverage\n"
        "- Mock ALL external I/O (HTTP, DB, filesystem, time)\n"
        "- Every function: at least 1 happy path + 2 error/edge cases\n"
        "- Use httpx.AsyncClient for FastAPI endpoint tests (never TestClient)\n"
        "- Use hypothesis for data-validation functions\n"
        "- Tests in tests/test_*.py (Python) and src/**/*.test.tsx (TypeScript)\n"
    ) + _BASE_OUTPUT_FORMAT,

    "Security Analyst": (
        "You are the Security Analyst of CoDevx.\n"
        "Framework: OWASP Top 10, ASVS Level 2, CWE Top 25.\n"
        "Tasks:\n"
        "1. Review all generated code for SQL injection, XSS, command injection,\n"
        "   broken auth, SSRF, hardcoded secrets, missing rate limiting, CORS misconfig\n"
        "2. Write docs/security_review_<task_id>.md (severity: CRITICAL/HIGH/MEDIUM/LOW)\n"
        "3. Provide patch files for any HIGH+ finding\n"
        "4. Record all findings in notes for team memory\n"
        "NO HIGH or CRITICAL findings may pass without a fix.\n"
    ) + _BASE_OUTPUT_FORMAT,

    "DevOps Engineer": (
        "You are the DevOps Engineer of CoDevx.\n"
        "Stack: Docker (distroless final stage), GitHub Actions, Kubernetes, Prometheus.\n"
        "\n"
        "SAFETY RULES — NEVER VIOLATE:\n"
        "1. Deploy jobs MUST use 'workflow_dispatch' trigger ONLY — never 'push' or 'pull_request'\n"
        "   to main. CI jobs (test/lint/build) may use push/pull_request triggers.\n"
        "2. All deploy jobs MUST declare an 'environment:' block (e.g. 'environment: staging'\n"
        "   or 'environment: production') so GitHub environment protection rules apply.\n"
        "3. Every generated workflow MUST start with this comment block:\n"
        "   # ============================================================\n"
        "   # CONFIGURE BEFORE USE\n"
        "   # Required GitHub secrets:\n"
        "   #   - REGISTRY_TOKEN  (container registry push access)\n"
        "   #   - KUBECONFIG      (base64-encoded kubeconfig, staging only)\n"
        "   # Required GitHub environments: 'staging', 'production'\n"
        "   # Production environment MUST have required reviewers set.\n"
        "   # ============================================================\n"
        "4. Never hardcode cloud credentials, account IDs, or IP addresses.\n"
        "5. Production deployments must require manual approval via GitHub environment reviewers.\n"
        "   Add a 'needs: [approve]' or separate 'deploy-prod' job that only runs on\n"
        "   workflow_dispatch with an explicit 'environment: production' block.\n"
        "6. Non-root containers — always add: USER nonroot or USER 65534\n"
        "7. Multi-stage Docker builds — minimal final image (distroless or alpine)\n"
        "8. Resource limits (CPU/memory) on all K8s pods\n"
        "9. Readiness and liveness probes on every service\n"
        "10. Secrets via env vars only — never baked into images\n"
        "\n"
        "Output: Dockerfile, .github/workflows/ci.yml, .github/workflows/deploy.yml,\n"
        "        k8s/*.yaml, monitoring/prometheus.yml\n"
        "Separate ci.yml (auto-triggers on PR) from deploy.yml (manual workflow_dispatch only).\n"
    ) + _BASE_OUTPUT_FORMAT,
}


# ============================================================
# 7. DISCORD BOT
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


class _NullChannel:
    """Stand-in Discord channel for orders submitted via MCP / REST (no Discord)."""

    async def send(self, *args: Any, **kwargs: Any) -> None:
        add_log(f"[REPORT] {str(args[0])[:500] if args else ''}")


class ApprovalView(discord.ui.View):
    def __init__(self, task: str) -> None:
        super().__init__(timeout=1800)
        self.task = task

    def _is_architect(self, interaction: discord.Interaction) -> bool:
        return MANAGER_DISCORD_ID == 0 or interaction.user.id == MANAGER_DISCORD_ID

    @discord.ui.button(label="✅  Approve Execution", style=discord.ButtonStyle.success, custom_id="approve")
    async def approve(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        if not self._is_architect(interaction):
            await interaction.response.send_message("⛔ Only the Architect can approve.", ephemeral=True)
            return
        await interaction.response.send_message("✅ **Plan Approved.** Team executing...", ephemeral=False)
        self.stop()
        asyncio.create_task(_dispatch_pipeline(interaction.channel, self.task))

    @discord.ui.button(label="❌  Reject / Modify", style=discord.ButtonStyle.danger, custom_id="reject")
    async def reject(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        if not self._is_architect(interaction):
            await interaction.response.send_message("⛔ Only the Architect can reject.", ephemeral=True)
            return
        await interaction.response.send_message("❌ **Plan Rejected.** Issue a revised order.", ephemeral=False)
        set_agent_status("Project Manager", "IDLE", "blue")
        SYSTEM_STATE["current_task"] = "None"
        add_log("[Project Manager] Task rejected. Team standing by.")
        self.stop()


@bot.event
async def on_ready() -> None:
    add_log(f"[DISCORD] Bridge connected as {bot.user}")


@bot.command(name="order")
async def receive_order(ctx: commands.Context, *, task: str) -> None:
    """!order <task description>  — issue in #orders channel"""
    if CH_ORDERS and ctx.channel.id != CH_ORDERS:
        await ctx.send(f"⚠️ Please issue orders in <#{CH_ORDERS}>.", delete_after=10)
        return

    add_log(f"[ORDER] Received: '{task}'")
    SYSTEM_STATE["current_task"] = task
    set_agent_status("Project Manager", "THINKING...", "blue")
    await ctx.send(f"🧠 **Project Manager** is analyzing: `{task}`...")
    await asyncio.sleep(3)

    plan = (
        f"### 📋 Execution Plan\n**Order:** {task}\n\n**Pipeline:**\n"
        f"1. 🟣 **Architect** — System design + ADR\n"
        f"2. 🔵 **Frontend Dev** + 🟢 **Backend Dev** *(parallel)* — Implement code\n"
        f"3. ⚫ **Database Engineer** — Schema + migrations\n"
        f"4. 🟡 **QA Engineer** — Tests ≥85% coverage gate\n"
        f"5. 🔴 **Security Analyst** — OWASP + ASVS scan\n"
        f"6. 🟠 **DevOps Engineer** — Docker + CI/CD\n"
        f"7. 🔵 **Project Manager** — Delivery report + memory\n\n"
        f"**LLM:** {'✅ ' + LLM_MODEL if LLM_ENABLED else '⚠️ Simulation (set OPENAI_API_KEY)'}\n"
        f"**Git:** {'✅ ' + (GITHUB_REPO or GIT_WORKSPACE) if GITHUB_TOKEN else '📁 Local workspace'}\n"
        f"**Tools:** {'✅ pytest + bandit enabled' if ENABLE_REAL_TOOLS else '⚠️ Simulated (ENABLE_REAL_TOOLS=false)'}\n\n"
        f"**Requires your approval ↓**"
    )

    set_agent_status("Project Manager", "WAITING APPROVAL", "yellow")
    add_log("[Project Manager] Plan ready. Awaiting approval in #plans.")

    plans_ch = bot.get_channel(CH_PLANS) if CH_PLANS else ctx.channel
    await (plans_ch or ctx.channel).send(plan, view=ApprovalView(task))


# ============================================================
# 8. EXECUTION PIPELINE  (LLM-powered, 8 agents)
# ============================================================

async def execute_pipeline(channel: Any, task: str) -> None:  # noqa: C901
    """
    Full 8-agent SDLC pipeline.
    LLM-powered when OPENAI_API_KEY is configured; gracefully simulates otherwise.
    """
    task_id = str(uuid.uuid4())[:8]
    branch  = f"feat/{task_id}"
    all_files: list[dict[str, Any]] = []
    tests_passed = 0
    bandit_clean = True
    pr_url: str | None = None

    await git_init_workspace()

    # ── Read the living project architecture document ─────────────────────────
    project_arch = _read_project_architecture()
    arch_project_ctx = (
        f"\n\n---\n**Existing Project Architecture** (extend this — do not contradict or redesign from scratch):\n{project_arch}"
        if project_arch
        else "\n\n(No existing project architecture file — this may be the first task for this project.)"
    )
    if project_arch:
        add_log("[PM] 📖 Loaded existing PROJECT_ARCHITECTURE.md for context injection.")

    try:
        # ── PHASE 1: Architect ───────────────────────────────────────────────
        set_agent_status("Architect", "DESIGNING...", "purple")
        add_log(f"[Architect] Designing solution for task {task_id}...")
        arch_memories = await db_recall_memories("Architect", MEMORY_CONTEXT_K)
        mem_ctx = "\n".join(f"- {m}" for m in arch_memories) or "No prior memories."
        arch_raw = await call_llm(
            "Architect",
            AGENT_SYSTEM_PROMPTS["Architect"],
            f"Task: {task}\n\nPast architecture memories:\n{mem_ctx}{arch_project_ctx}\n\nDesign the complete technical solution. IMPORTANT: if an existing project architecture is shown above, extend and refine it — do not redesign components that already exist.",
            temperature=0.4,
        )
        arch_result = _parse_agent_response(arch_raw)
        architecture_doc = arch_result.get("summary", "")
        for f in arch_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in arch_result.get("notes", []):
            await db_store_memory(task_id, "Architect", "architecture", note)
        add_log(f"[Architect] ✅ Design complete — {len(arch_result.get('files', []))} docs.")
        set_agent_status("Architect", "IDLE", "purple")

        # ── PHASE 2: Frontend + Backend (parallel) ───────────────────────────
        set_agent_status("Frontend Dev",    "CODING...", "cyan")
        set_agent_status("Backend Dev",     "CODING...", "green")
        set_agent_status("Project Manager", "OBSERVING", "blue")
        add_log("[Frontend Dev] Implementing React components...")
        add_log("[Backend Dev]  Implementing FastAPI endpoints...")

        async def _run_frontend() -> dict[str, Any]:
            mems = await db_recall_memories("Frontend Dev", MEMORY_CONTEXT_K)
            mem = "\n".join(f"- {m}" for m in mems) or "No prior memories."
            raw = await call_llm(
                "Frontend Dev",
                AGENT_SYSTEM_PROMPTS["Frontend Dev"],
                f"Task: {task}\n\nArchitecture:\n{architecture_doc}{arch_project_ctx}\n\nPast memories:\n{mem}\n\nImplement all required frontend components.",
                temperature=0.6,
            )
            return _parse_agent_response(raw)

        async def _run_backend() -> dict[str, Any]:
            mems = await db_recall_memories("Backend Dev", MEMORY_CONTEXT_K)
            mem = "\n".join(f"- {m}" for m in mems) or "No prior memories."
            raw = await call_llm(
                "Backend Dev",
                AGENT_SYSTEM_PROMPTS["Backend Dev"],
                f"Task: {task}\n\nArchitecture:\n{architecture_doc}{arch_project_ctx}\n\nPast memories:\n{mem}\n\nImplement all required backend routes and services.",
                temperature=0.4,
            )
            return _parse_agent_response(raw)

        fe_result, be_result = await asyncio.gather(_run_frontend(), _run_backend())
        for f in fe_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in fe_result.get("notes", []):
            await db_store_memory(task_id, "Frontend Dev", "code_pattern", note)
        for f in be_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in be_result.get("notes", []):
            await db_store_memory(task_id, "Backend Dev", "code_pattern", note)
        add_log(f"[Frontend Dev] ✅ {len(fe_result.get('files', []))} components written.")
        add_log(f"[Backend Dev]  ✅ {len(be_result.get('files', []))} endpoints written.")
        set_agent_status("Frontend Dev", "IDLE", "cyan")
        set_agent_status("Backend Dev",  "IDLE", "green")

        # ── PHASE 3: Database Engineer ────────────────────────────────────────
        set_agent_status("Database Engineer", "MIGRATING...", "gray")
        add_log("[Database Engineer] Analysing schema requirements...")
        mems = await db_recall_memories("Database Engineer", MEMORY_CONTEXT_K)
        mem = "\n".join(f"- {m}" for m in mems) or "No prior memories."
        db_raw = await call_llm(
            "Database Engineer",
            AGENT_SYSTEM_PROMPTS["Database Engineer"],
            (
                f"Task: {task}\n\nArchitecture:\n{architecture_doc}{arch_project_ctx}\n\n"
                f"Backend summary: {be_result.get('summary', '')}\n\nPast memories:\n{mem}\n\n"
                "Design the database schema and required migrations."
            ),
            temperature=0.25,
        )
        db_result = _parse_agent_response(db_raw)
        for f in db_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in db_result.get("notes", []):
            await db_store_memory(task_id, "Database Engineer", "schema", note)
        add_log(f"[Database Engineer] ✅ {len(db_result.get('files', []))} schema files.")
        set_agent_status("Database Engineer", "IDLE", "gray")

        # ── PHASE 4: QA Engineer ──────────────────────────────────────────────
        set_agent_status("QA Engineer", "TESTING...", "yellow")
        add_log("[QA Engineer] Writing test suites...")
        mems = await db_recall_memories("QA Engineer", MEMORY_CONTEXT_K)
        mem = "\n".join(f"- {m}" for m in mems) or "No prior memories."
        generated_summary = "\n".join(f"- {f['path']}" for f in all_files)
        qa_raw = await call_llm(
            "QA Engineer",
            AGENT_SYSTEM_PROMPTS["QA Engineer"],
            (
                f"Task: {task}\n\nGenerated files:\n{generated_summary}{arch_project_ctx}\n\n"
                f"Backend summary: {be_result.get('summary', '')}\n"
                f"Frontend summary: {fe_result.get('summary', '')}\n\nPast memories:\n{mem}\n\n"
                "Write comprehensive tests for all generated code."
            ),
            temperature=0.3,
        )
        qa_result = _parse_agent_response(qa_raw)
        for f in qa_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in qa_result.get("notes", []):
            await db_store_memory(task_id, "QA Engineer", "test_pattern", note)
        py_passed, py_out, tests_passed = await run_pytest(GIT_WORKSPACE)
        if ENABLE_REAL_TOOLS:
            add_log(f"[QA Engineer] pytest: {'✅ PASS' if py_passed else '❌ FAIL'} — {tests_passed} tests")
            if py_out.strip():
                add_log(f"[QA Engineer] {py_out[:300]}")
        else:
            add_log(f"[QA Engineer] ✅ {len(qa_result.get('files', []))} test files written.")
        set_agent_status("QA Engineer", "IDLE", "yellow")

        # ── PHASE 5: Security Analyst ─────────────────────────────────────────
        set_agent_status("Security Analyst", "SCANNING...", "red")
        add_log("[Security Analyst] Running OWASP/ASVS code review...")
        mems = await db_recall_memories("Security Analyst", MEMORY_CONTEXT_K)
        mem = "\n".join(f"- {m}" for m in mems) or "No prior findings."
        sec_raw = await call_llm(
            "Security Analyst",
            AGENT_SYSTEM_PROMPTS["Security Analyst"],
            (
                f"Task: {task}\n\nGenerated files:\n{generated_summary}\n\n"
                f"Architecture: {architecture_doc}{arch_project_ctx}\n\nPast security findings:\n{mem}\n\n"
                f"Review all generated code for OWASP Top 10 and CWE Top 25 vulnerabilities."
            ),
            temperature=0.2,
        )
        sec_result = _parse_agent_response(sec_raw)
        for f in sec_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in sec_result.get("notes", []):
            await db_store_memory(task_id, "Security Analyst", "security_finding", note)
        bandit_clean, bandit_out = await run_bandit(GIT_WORKSPACE)
        if ENABLE_REAL_TOOLS:
            add_log(f"[Security Analyst] bandit: {'✅ CLEAN' if bandit_clean else '⚠️ FINDINGS'}")
            if not bandit_clean:
                add_log(f"[Security Analyst] {bandit_out[:300]}")
        add_log(f"[Security Analyst] ✅ {len(sec_result.get('files', []))} security docs written.")
        set_agent_status("Security Analyst", "IDLE", "red")

        # ── PHASE 6: DevOps Engineer ──────────────────────────────────────────
        set_agent_status("DevOps Engineer", "DEPLOYING...", "orange")
        add_log("[DevOps Engineer] Writing Dockerfile + CI/CD pipeline...")
        mems = await db_recall_memories("DevOps Engineer", MEMORY_CONTEXT_K)
        mem = "\n".join(f"- {m}" for m in mems) or "No prior memories."
        dv_raw = await call_llm(
            "DevOps Engineer",
            AGENT_SYSTEM_PROMPTS["DevOps Engineer"],
            (
                f"Task: {task}\n\nGenerated files:\n{generated_summary}{arch_project_ctx}\n\nPast experience:\n{mem}\n\n"
                "Create Dockerfile, GitHub Actions CI/CD workflow, and K8s manifests."
            ),
            temperature=0.35,
        )
        dv_result = _parse_agent_response(dv_raw)
        for f in dv_result.get("files", []):
            await write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)
        for note in dv_result.get("notes", []):
            await db_store_memory(task_id, "DevOps Engineer", "infra_pattern", note)
        add_log(f"[DevOps Engineer] ✅ {len(dv_result.get('files', []))} infra files written.")
        set_agent_status("DevOps Engineer", "IDLE", "orange")

        # ── ARCHITECTURE DOC UPDATE (before git commit) ───────────────────────
        add_log("[PM] Updating living project architecture document...")
        arch_update = await call_llm(
            "Project Manager",
            (
                "You are a senior technical writer maintaining a living architecture document for a software project. "
                "Output ONLY a clean Markdown document — no JSON, no code fences wrapping the whole document, "
                "no commentary. Preserve all existing sections and content. Add or update sections as needed."
            ),
            (
                f"Existing project architecture:\n{project_arch or '(none — create a new document)'}\n\n"
                f"Completed task: {task}\n\n"
                f"Architect design summary:\n{architecture_doc}\n\n"
                f"New files added in this task:\n" + "\n".join(f"- {f['path']}" for f in all_files) + "\n\n"
                "Update the architecture document to reflect this task's additions. "
                "Add/update sections for: new API endpoints, data models, React components, "
                "database schema changes, and any key architectural decisions made."
            ),
            temperature=0.3,
        )
        await write_workspace_file(task_id, "docs/PROJECT_ARCHITECTURE.md", arch_update)
        all_files.append({"path": "docs/PROJECT_ARCHITECTURE.md", "content": arch_update})
        add_log("[PM] ✅ docs/PROJECT_ARCHITECTURE.md updated and queued for commit.")

        # ── PHASE 7: Git commit + PR ─────────────────────────────────────────
        all_file_paths = [f["path"] for f in all_files]
        infra_detected = _detect_infra_files(all_file_paths)
        add_log(f"[GIT] Committing {len(all_files)} files to branch {branch}...")
        if infra_detected:
            add_log(
                f"[GIT][INFRA GATE] ⚠️  {len(infra_detected)} infrastructure file(s) in this delivery — "
                "PR will carry mandatory review checklist."
            )
        pr_url = await git_commit_push(task_id, branch, all_file_paths)
        add_log(f"[GIT] ✅ {'PR opened: ' + pr_url if pr_url else 'Committed to ' + branch}")

        # ── PHASE 8: Project Manager — Delivery Report ───────────────────────
        set_agent_status("Project Manager", "REPORTING...", "blue")
        add_log("[Project Manager] Compiling delivery report...")
        mems = await db_recall_memories("Project Manager", MEMORY_CONTEXT_K)
        mem = "\n".join(f"- {m}" for m in mems) or "No prior deliveries."
        pm_raw = await call_llm(
            "Project Manager",
            AGENT_SYSTEM_PROMPTS["Project Manager"],
            (
                f"Completed task: {task}\nTask ID: {task_id}\n\n"
                f"Files generated ({len(all_files)}):\n{generated_summary}\n\n"
                f"Tests passed: {tests_passed} | Branch: {branch} | PR: {pr_url or 'N/A'}\n"
                f"Past deliveries:\n{mem}\n\nWrite a concise delivery report."
            ),
            temperature=0.3,
        )
        pm_result = _parse_agent_response(pm_raw)
        for note in pm_result.get("notes", []):
            await db_store_memory(task_id, "Project Manager", "delivery", note)

        report = (
            f"## 🚀 Task Complete — `{task}`\n"
            f"**ID:** `{task_id}` | **Branch:** `{branch}`"
            + (f" | [PR]({pr_url})" if pr_url else "") + "\n\n"
            f"- 📂 **{len(all_files)} files** generated\n"
            f"- ✅ **{tests_passed} tests** passed\n"
            f"- 🔒 Security: {'✅ CLEAN' if bandit_clean else '⚠️ review required'}\n"
            f"- 🤖 LLM: {'✅ ' + LLM_MODEL if LLM_ENABLED else '⚠️ simulation mode'}\n"
            + (
                f"- ⚠️ **INFRA GATE:** {len(infra_detected)} infra file(s) — "
                "PR requires dedicated infrastructure review before merge.\n"
                if infra_detected else
                "- 🟢 No infrastructure files — standard code review applies.\n"
            )
            + "\n" + pm_result.get("summary", "")
        )

        task_record: dict[str, Any] = {
            "id": task_id,
            "description": task,
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files_modified": len(all_files),
            "tests_passed": tests_passed,
            "branch": branch,
            "pr_url": pr_url,
            "llm_used": int(LLM_ENABLED),
        }
        await db_save_task(task_record)
        SYSTEM_STATE["history"].insert(0, task_record)
        if len(SYSTEM_STATE["history"]) > 50:
            SYSTEM_STATE["history"] = SYSTEM_STATE["history"][:50]

        reports_ch = bot.get_channel(CH_REPORTS) if CH_REPORTS else channel
        await (reports_ch or channel).send(report)

    except Exception as exc:
        add_log(f"[ERROR] Pipeline failed: {exc}")
        try:
            await channel.send(f"❌ **Pipeline error:** `{exc}`")
        except Exception:
            pass

    finally:
        for name in SYSTEM_STATE["agents"]:
            SYSTEM_STATE["agents"][name]["status"] = "IDLE"
        SYSTEM_STATE["current_task"] = "None"
        asyncio.create_task(_broadcast())
        add_log("[Project Manager] ✅ Workflow complete. Team standing by.")


# ============================================================
# 9. FASTAPI APP
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    # ── DB init ─────────────────────────────────────────────
    await init_db()
    SYSTEM_STATE["history"] = await db_load_history()
    add_log(f"[DB] SQLite initialised at {DB_PATH}")
    # ── AgentScope init ──────────────────────────────────────
    if _AGENTSCOPE_IMPORTABLE and AGENTSCOPE_ENABLED:
        as_cfg = init_agentscope()
        if as_cfg and as_cfg.enabled:
            SYSTEM_STATE["agentscope_enabled"] = True
            SYSTEM_STATE["agentscope_config"] = as_cfg
            add_log(
                f"[AgentScope] ✅ Active — model={as_cfg.model_name} "
                f"msghub_rounds={as_cfg.msghub_rounds}"
            )
        else:
            add_log("[AgentScope] Disabled or unavailable — using legacy pipeline.")
    else:
        add_log("[AgentScope] Not enabled (AGENTSCOPE_ENABLED=false or package missing).")
    # ── Discord bridge ───────────────────────────────────────
    if not DISCORD_TOKEN:
        add_log("[WARN] DISCORD_TOKEN not set — Discord bridge disabled.")
        yield
        await _db.close() if _db else None  # type: ignore[union-attr]
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
    if _db:
        await _db.close()


app = FastAPI(title="CoDevx — Agent Mesh", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# Pipeline dispatcher — routes to AgentScope pipeline or legacy fallback
# ---------------------------------------------------------------------------

async def _dispatch_pipeline(channel: Any, task: str) -> None:
    """
    Dispatch to execute_agentscope_pipeline() when AgentScope is active,
    or fall back to the legacy execute_pipeline() otherwise.

    This is the single call site that all 4 entry points use:
      - POST /api/order
      - Discord !order (via ApprovalView.approve)
      - POST /webhook/zeroclaw
      - POST /webhook/whatsapp
      - MCP codevx_submit_order
    """
    if (
        SYSTEM_STATE.get("agentscope_enabled")
        and _AS_PIPELINE_IMPORTABLE
        and AGENTSCOPE_ENABLED
    ):
        await execute_agentscope_pipeline(channel, task)
    else:
        await execute_pipeline(channel, task)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)
    await websocket.send_text(
        json.dumps({"type": "state_update", "payload": SYSTEM_STATE})
    )
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        _ws_clients.discard(websocket)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "4.0.0"}


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return SYSTEM_STATE


@app.get("/api/agents/{name}")
async def get_agent(name: str) -> dict[str, Any]:
    agent = SYSTEM_STATE["agents"].get(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found.")
    return {"name": name, **agent}


@app.get("/api/history")
async def get_history() -> list[Any]:
    return SYSTEM_STATE["history"]


@app.get("/api/files/{task_id}")
async def get_task_files(task_id: str) -> list[dict[str, Any]]:
    """Return metadata for all files generated by a specific task."""
    files = await db_get_files(task_id)
    if not files:
        raise HTTPException(status_code=404, detail=f"No files found for task '{task_id}'")
    # Return path + created_at only (omit content to keep response small)
    return [{"path": f["file_path"], "created_at": f["created_at"]} for f in files]


class _OrderBody(BaseModel):
    task: str


@app.post("/api/order")
async def submit_order(body: _OrderBody) -> dict[str, str]:
    """Submit a task order directly from the dashboard UI (no Discord required)."""
    task = body.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="'task' is required")
    if SYSTEM_STATE["current_task"] != "None":
        raise HTTPException(status_code=409, detail="A task is already running. Wait for it to finish.")
    task_id = str(uuid.uuid4())[:8]
    add_log(f"[API] Order via REST: '{task}' (id={task_id})")
    SYSTEM_STATE["current_task"] = task
    asyncio.create_task(_dispatch_pipeline(_NullChannel(), task))
    return {"status": "accepted", "task_id": task_id, "task": task}


# ── Webhook: ZeroClaw ─────────────────────────────────────────────────────────

def _verify_hmac(secret: str, body: bytes, sig_header: str) -> bool:
    """Constant-time HMAC-SHA256 verification."""
    if not secret:
        return True  # dev mode — no secret configured
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.lstrip("sha256="))


@app.post("/webhook/zeroclaw")
async def webhook_zeroclaw(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    sig = request.headers.get("X-ZeroClaw-Signature", "")
    if ZEROCLAW_SECRET and not _verify_hmac(ZEROCLAW_SECRET, raw_body, sig):
        raise HTTPException(status_code=401, detail="Invalid ZeroClaw signature")
    try:
        data: dict[str, Any] = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    task = str(data.get("task", "")).strip()
    if not task:
        raise HTTPException(status_code=400, detail="'task' field is required")
    reply_url: str | None = data.get("reply_url")
    add_log(f"[ZeroClaw] Order received: '{task}'")
    SYSTEM_STATE["current_task"] = task

    async def _run_and_reply() -> None:
        await _dispatch_pipeline(_NullChannel(), task)
        if reply_url:
            try:
                import httpx
                report = [e for e in SYSTEM_STATE["logs"][-30:] if "✅" in e or task[:20] in e]
                async with httpx.AsyncClient(timeout=15.0) as client:
                    await client.post(reply_url, json={"message": "\n".join(report)})
            except Exception as exc:
                add_log(f"[ZeroClaw][WARN] reply callback failed: {exc}")

    asyncio.create_task(_run_and_reply())
    return {"status": "accepted", "task": task}


# ── Webhook: WhatsApp / Twilio ────────────────────────────────────────────────

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request) -> dict[str, str]:
    form = await request.form()
    sender: str = str(form.get("From", ""))
    body: str   = str(form.get("Body", "")).strip()

    if MANAGER_WHATSAPP and sender != MANAGER_WHATSAPP:
        add_log(f"[WHATSAPP][WARN] Rejected message from {sender}")
        raise HTTPException(status_code=403, detail="Unauthorised sender")

    lower = body.lower()

    if lower.startswith("order "):
        task = body[6:].strip()
        if not task:
            return {"status": "ignored", "reason": "empty task"}
        add_log(f"[WHATSAPP] Order from {sender}: '{task}'")
        SYSTEM_STATE["current_task"] = task
        asyncio.create_task(_dispatch_pipeline(_NullChannel(), task))
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN_:
            try:
                from twilio.rest import Client as TwilioClient
                TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN_).messages.create(
                    body=f"✅ Order received: {task}\nPipeline started. I'll notify you when done.",
                    from_=TWILIO_FROM or sender,
                    to=sender,
                )
            except Exception as exc:
                add_log(f"[TWILIO][WARN] Reply failed: {exc}")
        return {"status": "accepted", "task": task}

    if lower in {"approve", "yes", "✅"}:
        add_log(f"[WHATSAPP] Approval received from {sender}")
        return {"status": "approval_noted"}

    if lower in {"reject", "no", "❌"}:
        add_log(f"[WHATSAPP] Rejection from {sender}")
        SYSTEM_STATE["current_task"] = "None"
        for name in SYSTEM_STATE["agents"]:
            SYSTEM_STATE["agents"][name]["status"] = "IDLE"
        asyncio.create_task(_broadcast())
        return {"status": "rejected"}

    return {"status": "ignored", "reason": "unknown command"}


# ============================================================
# 10.  MCP SERVER  (VS Code Copilot · Cursor · Antigravity)
# ============================================================

_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "codevx_submit_order",
        "description": "Submit a development task to the CoDevx 8-agent SDLC pipeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the feature or task to build",
                }
            },
            "required": ["task"],
        },
    },
    {
        "name": "codevx_get_state",
        "description": "Get current status of all 8 agents and the active task.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "codevx_get_history",
        "description": "List completed tasks with id, description, timestamp.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "codevx_get_logs",
        "description": "Get recent pipeline activity logs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent log entries to return (default 50)",
                    "default": 50,
                }
            },
        },
    },
    {
        "name": "codevx_get_agent",
        "description": "Get status of a specific agent by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Agent name",
                    "enum": [
                        "Project Manager", "Architect", "Frontend Dev", "Backend Dev",
                        "QA Engineer", "DevOps Engineer", "Security Analyst", "Database Engineer",
                    ],
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "codevx_get_agentscope_status",
        "description": (
            "Get AgentScope integration status including model config, "
            "memory backend, and hub topology."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_MCP_SERVER_INFO: dict[str, Any] = {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "codevx", "version": "4.0.0"},
    "capabilities": {"tools": {}},
}


@app.get("/mcp")
async def mcp_capabilities() -> dict[str, Any]:
    """MCP discovery — read by VS Code Copilot, Cursor AI, and Antigravity."""
    return _MCP_SERVER_INFO


@app.post("/mcp")  # noqa: C901
async def mcp_dispatch(request: Request) -> dict[str, Any]:
    """JSON-RPC 2.0 MCP endpoint — handles tool calls from IDE AI agents."""
    body: dict[str, Any] = await request.json()
    rpc_id = body.get("id")
    method: str = body.get("method", "")
    params: dict[str, Any] = body.get("params") or {}

    def _ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def _err(code: int, msg: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": msg}}

    try:
        if method == "initialize":
            return _ok(_MCP_SERVER_INFO)

        if method == "tools/list":
            return _ok({"tools": _MCP_TOOLS})

        if method == "tools/call":
            tool: str = params.get("name", "")
            args: dict[str, Any] = params.get("arguments") or {}

            if tool == "codevx_submit_order":
                task = str(args.get("task", "")).strip()
                if not task:
                    return _err(-32602, "'task' argument is required")
                if SYSTEM_STATE["current_task"] != "None":
                    return _err(-32602, "Pipeline busy — a task is already running")
                task_id = str(uuid.uuid4())[:8]
                add_log(f"[MCP] Order via IDE: '{task}' (id={task_id})")
                SYSTEM_STATE["current_task"] = task
                asyncio.create_task(_dispatch_pipeline(_NullChannel(), task))
                return _ok({"content": [{"type": "text", "text": (
                    f"\u2705 Order submitted — task_id `{task_id}`.\n"
                    "Pipeline started. Check status with `codevx_get_state` or visit http://localhost:8000"
                )}]})

            if tool == "codevx_get_state":
                return _ok({"content": [{"type": "text", "text": json.dumps(SYSTEM_STATE, indent=2)}]})

            if tool == "codevx_get_history":
                return _ok({"content": [{"type": "text", "text": json.dumps(SYSTEM_STATE["history"], indent=2)}]})

            if tool == "codevx_get_logs":
                limit = max(1, min(int(args.get("limit", 50)), 200))
                logs = SYSTEM_STATE["logs"][-limit:]
                return _ok({"content": [{"type": "text", "text": "\n".join(logs)}]})

            if tool == "codevx_get_agent":
                name = str(args.get("name", ""))
                agent = SYSTEM_STATE["agents"].get(name)
                if not agent:
                    return _err(-32602, f"Agent '{name}' not found")
                return _ok({"content": [{"type": "text", "text": json.dumps({"name": name, **agent}, indent=2)}]})

            if tool == "codevx_get_agentscope_status":
                as_cfg = SYSTEM_STATE.get("agentscope_config")
                if as_cfg and hasattr(as_cfg, "enabled"):
                    status = {
                        "enabled": as_cfg.enabled,
                        "model": as_cfg.model_name if as_cfg.enabled else None,
                        "model_type": as_cfg.model_type if as_cfg.enabled else None,
                        "model_config_name": as_cfg.model_config_name if as_cfg.enabled else None,
                        "memory_backend": as_cfg.memory_backend if as_cfg.enabled else None,
                        "hub_topology": as_cfg.hub_topology if as_cfg.enabled else None,
                        "msghub_rounds": as_cfg.msghub_rounds if as_cfg.enabled else None,
                        "extra": as_cfg.extra if as_cfg.enabled else {},
                    }
                else:
                    status = {
                        "enabled": False,
                        "reason": "AgentScope not initialized or not installed.",
                    }
                return _ok({"content": [{"type": "text", "text": json.dumps(status, indent=2)}]})

            return _err(-32601, f"Unknown tool: '{tool}'")

        if method == "ping":
            return _ok({})  # keep-alive

        return _err(-32601, f"Unknown method: '{method}'")

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
            "CoDevx Agent Mesh v3.0 running.<br>"
            "Open the React Command Center at :3000 (Docker) or :5173 (Vite dev).</h1>"
        )


# ============================================================
# 11. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  🤖  CODEVX — AGENT MESH v4.0  (AgentScope Edition)")
    print("=" * 60)
    print(f"  🧠  LLM:        {'✅ ' + LLM_MODEL if LLM_ENABLED else '⚠️  Simulation (set OPENAI_API_KEY)'}")
    print(f"  🔗  AgentScope: {'✅ enabled (MsgHub + self-correcting loops)' if AGENTSCOPE_ENABLED else '⚠️  disabled (AGENTSCOPE_ENABLED=false)'}")
    print(f"  💾  DB:         {DB_PATH}")
    print(f"  📁  Workspace:  {GIT_WORKSPACE}")
    print(f"  🔧  Tools:      {'✅ pytest + bandit' if ENABLE_REAL_TOOLS else '⚠️  Simulated'}")
    print("  🌐  REST API:   http://localhost:8000/api/state")
    print("  📬  Order:      POST http://localhost:8000/api/order")
    print("  ⚡  WebSocket:  ws://localhost:8000/ws/state")
    print("  🤝  MCP Server: http://localhost:8000/mcp")
    print("  📱  React UI:   http://localhost:3000  (Docker)")
    print("  🔧  Dev UI:     http://localhost:5173  (Vite dev)")
    print("  📖  API Docs:   http://localhost:8000/docs")
    print("=" * 60)
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")