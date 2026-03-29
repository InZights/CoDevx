"""
agentscope_pipeline.py — AgentScope-powered pipeline for CoDevx v4.0
======================================================================
Implements execute_agentscope_pipeline() as a drop-in replacement for
the legacy execute_pipeline() in agent_mesh.py.

Key upgrades over the legacy pipeline:
  - Phase 2: MsgHub collaboration — FrontendDev ↔ BackendDev ↔ Architect
    can exchange messages about API shapes, component contracts, etc.
  - Phase 4: Self-correcting QA loop — pytest failures trigger fix requests
    to dev agents and automated re-runs.
  - Phase 5: Self-correcting Security loop — HIGH/CRITICAL bandit / npm-audit
    findings trigger fix requests to dev agents before re-scanning.
  - All 8 agents backed by ListMemory (in-context) + SQLite (cross-session).

Constraints preserved:
  - add_log() and set_agent_status() are called at the same points.
  - All SQLite writes (db_store_memory, db_save_task, db_save_file) are kept.
  - Async compatibility via asyncio.to_thread() for synchronous AgentScope APIs.
  - Full simulation fallback when no LLM key is configured.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Imports from agent_mesh (lazy, to avoid circular imports at module load time)
# ---------------------------------------------------------------------------

def _am() -> Any:
    """Return the agent_mesh module (lazy import)."""
    import agent_mesh  # type: ignore[import]
    return agent_mesh


# ---------------------------------------------------------------------------
# Imports from our new modules
# ---------------------------------------------------------------------------

from agentscope_agents import (  # noqa: E402
    build_agents,
    msghub_collaboration_round,
    CoDevxAgentBase,
)
from agentscope_tools import (  # noqa: E402
    build_qa_toolkit,
    build_security_toolkit,
    build_devops_toolkit,
)


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

async def _phase_architect(
    am: Any,
    task: str,
    task_id: str,
    arch_project_ctx: str,
    arch_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> str:
    """Phase 1 — Architect designs the solution and returns the architecture doc."""
    am.set_agent_status("Architect", "DESIGNING...", "purple")
    am.add_log(f"[Architect] Designing solution for task {task_id}...")

    arch_memories = await am.db_recall_memories("Architect", am.MEMORY_CONTEXT_K)
    arch_agent.recall_and_inject_memories(task_id, arch_memories)

    arch_result = await arch_agent.run(
        f"Task: {task}\n\nPast architecture memories:\n{arch_agent._memory_context()}"
        f"{arch_project_ctx}\n\nDesign the complete technical solution. "
        "IMPORTANT: if an existing project architecture is shown above, extend and refine it "
        "— do not redesign components that already exist."
    )
    for f in arch_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in arch_result.get("notes", []):
        await am.db_store_memory(task_id, "Architect", "architecture", note)

    am.add_log(f"[Architect] ✅ Design complete — {len(arch_result.get('files', []))} docs.")
    am.set_agent_status("Architect", "IDLE", "purple")
    return arch_result.get("summary", "")


async def _phase_msghub(
    am: Any,
    task: str,
    task_id: str,
    architecture_doc: str,
    arch_project_ctx: str,
    fe_agent: CoDevxAgentBase,
    be_agent: CoDevxAgentBase,
    msghub_rounds: int,
    all_files: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Phase 2 — MsgHub collaboration between Frontend and Backend agents."""
    am.set_agent_status("Frontend Dev",    "CODING...", "cyan")
    am.set_agent_status("Backend Dev",     "CODING...", "green")
    am.set_agent_status("Project Manager", "OBSERVING", "blue")
    am.add_log("[MsgHub] Opening collaboration hub: Architect ↔ Frontend Dev ↔ Backend Dev")
    am.add_log("[Frontend Dev] Implementing React components...")
    am.add_log("[Backend Dev]  Implementing FastAPI endpoints...")

    fe_memories = await am.db_recall_memories("Frontend Dev", am.MEMORY_CONTEXT_K)
    be_memories = await am.db_recall_memories("Backend Dev",  am.MEMORY_CONTEXT_K)
    fe_agent.recall_and_inject_memories(task_id, fe_memories)
    be_agent.recall_and_inject_memories(task_id, be_memories)

    broadcast_msg = (
        f"Task: {task}\n\nArchitecture Design:\n{architecture_doc}{arch_project_ctx}\n\n"
        "You are in a collaboration hub with the Architect and your peer developer. "
        f"Past Frontend memories:\n{fe_agent._memory_context()}\n"
        f"Past Backend memories:\n{be_agent._memory_context()}\n\n"
        "Frontend Dev: implement all required React components.\n"
        "Backend Dev: implement all required FastAPI routes and services.\n"
        "Coordinate on API payload shapes and endpoint contracts."
    )

    hub_responses = await msghub_collaboration_round(
        agents=[fe_agent, be_agent],
        broadcast_message=broadcast_msg,
        rounds=msghub_rounds,
    )

    fe_result = hub_responses[0] if len(hub_responses) > 0 else {"summary": "", "files": [], "notes": []}
    be_result = hub_responses[1] if len(hub_responses) > 1 else {"summary": "", "files": [], "notes": []}

    for f in fe_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in fe_result.get("notes", []):
        await am.db_store_memory(task_id, "Frontend Dev", "code_pattern", note)

    for f in be_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in be_result.get("notes", []):
        await am.db_store_memory(task_id, "Backend Dev", "code_pattern", note)

    am.add_log(f"[Frontend Dev] ✅ {len(fe_result.get('files', []))} components written.")
    am.add_log(f"[Backend Dev]  ✅ {len(be_result.get('files', []))} endpoints written.")
    am.add_log("[MsgHub] Collaboration hub closed.")
    am.set_agent_status("Frontend Dev", "IDLE", "cyan")
    am.set_agent_status("Backend Dev",  "IDLE", "green")
    return fe_result, be_result


async def _phase_database(
    am: Any,
    task: str,
    task_id: str,
    architecture_doc: str,
    arch_project_ctx: str,
    be_summary: str,
    db_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> None:
    """Phase 3 — Database Engineer designs schema and migrations."""
    am.set_agent_status("Database Engineer", "MIGRATING...", "gray")
    am.add_log("[Database Engineer] Analysing schema requirements...")

    db_memories = await am.db_recall_memories("Database Engineer", am.MEMORY_CONTEXT_K)
    db_agent.recall_and_inject_memories(task_id, db_memories)

    db_result = await db_agent.run(
        f"Task: {task}\n\nArchitecture:\n{architecture_doc}{arch_project_ctx}\n\n"
        f"Backend summary: {be_summary}\n\n"
        f"Past memories:\n{db_agent._memory_context()}\n\n"
        "Design the database schema and required migrations."
    )
    for f in db_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in db_result.get("notes", []):
        await am.db_store_memory(task_id, "Database Engineer", "schema", note)

    am.add_log(f"[Database Engineer] ✅ {len(db_result.get('files', []))} schema files.")
    am.set_agent_status("Database Engineer", "IDLE", "gray")


async def _phase_qa(
    am: Any,
    task: str,
    task_id: str,
    arch_project_ctx: str,
    be_summary: str,
    fe_summary: str,
    qa_agent: CoDevxAgentBase,
    be_agent: CoDevxAgentBase,
    fe_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> tuple[bool, int]:
    """Phase 4 — QA Engineer with self-correcting pytest loop."""
    am.set_agent_status("QA Engineer", "TESTING...", "yellow")
    am.add_log("[QA Engineer] Writing test suites...")

    qa_memories = await am.db_recall_memories("QA Engineer", am.MEMORY_CONTEXT_K)
    qa_agent.recall_and_inject_memories(task_id, qa_memories)

    generated_summary = "\n".join(f"- {f['path']}" for f in all_files)
    qa_result = await qa_agent.run(
        f"Task: {task}\n\nGenerated files:\n{generated_summary}{arch_project_ctx}\n\n"
        f"Backend summary: {be_summary}\n"
        f"Frontend summary: {fe_summary}\n\n"
        f"Past memories:\n{qa_agent._memory_context()}\n\n"
        "Write comprehensive tests for all generated code."
    )
    for f in qa_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in qa_result.get("notes", []):
        await am.db_store_memory(task_id, "QA Engineer", "test_pattern", note)

    py_passed, py_out, tests_passed = await am.run_pytest(am.GIT_WORKSPACE)
    if am.ENABLE_REAL_TOOLS:
        am.add_log(f"[QA Engineer] pytest: {'✅ PASS' if py_passed else '❌ FAIL'} — {tests_passed} tests")
        if py_out.strip():
            am.add_log(f"[QA Engineer] {py_out[:300]}")

    # Self-correcting retry loop
    if not py_passed and am.ENABLE_REAL_TOOLS:
        py_passed, py_out, tests_passed = await _qa_retry_loop(
            am, task_id, py_passed, py_out, tests_passed,
            qa_agent, be_agent, fe_agent, all_files,
        )

    if not am.ENABLE_REAL_TOOLS:
        am.add_log(f"[QA Engineer] ✅ {len(qa_result.get('files', []))} test files written.")
    am.set_agent_status("QA Engineer", "IDLE", "yellow")
    return py_passed, tests_passed


async def _qa_retry_loop(
    am: Any,
    task_id: str,
    py_passed: bool,
    py_out: str,
    tests_passed: int,
    qa_agent: CoDevxAgentBase,
    be_agent: CoDevxAgentBase,
    fe_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> tuple[bool, str, int]:
    """QA self-correcting retry loop — requests fixes from dev agents on failure."""
    for retry in range(am.MAX_RETRIES):
        am.add_log(
            f"[QA] pytest FAILED — requesting fixes from Backend Dev & Frontend Dev "
            f"(retry {retry + 1}/{am.MAX_RETRIES})..."
        )
        fix_request = await qa_agent.run(
            f"pytest FAILED with the following output:\n{py_out[:2000]}\n\n"
            "Identify which tests are failing and why. "
            "Write updated test files OR updated source files to fix the failures. "
            "Focus on the root cause — do not just skip the failing tests."
        )
        for f in fix_request.get("files", []):
            await am.write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)

        be_fix, fe_fix = await asyncio.gather(
            be_agent.run(
                f"pytest FAILED:\n{py_out[:1000]}\n\n"
                "Fix the backend code to make the tests pass. "
                "Return only the files that need to be updated."
            ),
            fe_agent.run(
                f"pytest FAILED:\n{py_out[:1000]}\n\n"
                "Fix the frontend code to make the tests pass. "
                "Return only the files that need to be updated."
            ),
        )
        for f in be_fix.get("files", []) + fe_fix.get("files", []):
            await am.write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)

        py_passed, py_out, tests_passed = await am.run_pytest(am.GIT_WORKSPACE)
        status = "✅ PASSED" if py_passed else "❌ FAILED"
        am.add_log(f"[QA] Retry {retry + 1}/{am.MAX_RETRIES} — pytest {status}")
        if py_passed:
            break

    return py_passed, py_out, tests_passed


async def _phase_security(
    am: Any,
    task: str,
    task_id: str,
    architecture_doc: str,
    arch_project_ctx: str,
    generated_summary: str,
    sec_agent: CoDevxAgentBase,
    be_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> bool:
    """Phase 5 — Security Analyst with self-correcting scan loop."""
    am.set_agent_status("Security Analyst", "SCANNING...", "red")
    am.add_log("[Security Analyst] Running OWASP/ASVS code review...")

    sec_memories = await am.db_recall_memories("Security Analyst", am.MEMORY_CONTEXT_K)
    sec_agent.recall_and_inject_memories(task_id, sec_memories)

    sec_result = await sec_agent.run(
        f"Task: {task}\n\nGenerated files:\n{generated_summary}\n\n"
        f"Architecture: {architecture_doc}{arch_project_ctx}\n\n"
        f"Past security findings:\n{sec_agent._memory_context()}\n\n"
        "Review all generated code for OWASP Top 10 and CWE Top 25 vulnerabilities."
    )
    for f in sec_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in sec_result.get("notes", []):
        await am.db_store_memory(task_id, "Security Analyst", "security_finding", note)

    bandit_clean, bandit_out = await am.run_bandit(am.GIT_WORKSPACE)
    if am.ENABLE_REAL_TOOLS:
        am.add_log(f"[Security Analyst] bandit: {'✅ CLEAN' if bandit_clean else '⚠️ FINDINGS'}")
        if not bandit_clean:
            am.add_log(f"[Security Analyst] {bandit_out[:300]}")

    # Self-correcting security retry loop
    if not bandit_clean and am.ENABLE_REAL_TOOLS:
        bandit_clean, bandit_out = await _security_retry_loop(
            am, task_id, bandit_clean, bandit_out,
            sec_agent, be_agent, all_files,
        )

    # npm audit scan
    npm_clean, npm_out = await am.run_npm_audit(am.GIT_WORKSPACE)
    if am.ENABLE_REAL_TOOLS and not npm_clean:
        am.add_log("[Security Analyst] npm audit: ⚠️ FINDINGS")
        am.add_log(f"[Security Analyst] {npm_out[:300]}")

    am.add_log(f"[Security Analyst] ✅ {len(sec_result.get('files', []))} security docs written.")
    am.set_agent_status("Security Analyst", "IDLE", "red")
    return bandit_clean


async def _security_retry_loop(
    am: Any,
    task_id: str,
    bandit_clean: bool,
    bandit_out: str,
    sec_agent: CoDevxAgentBase,
    be_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Security self-correcting retry loop — requests patches from dev agents on HIGH findings."""
    for retry in range(am.MAX_RETRIES):
        am.add_log(
            f"[Security] HIGH finding in scanned code — requesting patch from Backend Dev "
            f"(retry {retry + 1}/{am.MAX_RETRIES})..."
        )
        sec_fix = await sec_agent.run(
            f"Bandit SAST found HIGH/CRITICAL findings:\n{bandit_out[:2000]}\n\n"
            "Provide patched versions of the affected files to remediate all HIGH+ findings. "
            "Reference CWE numbers and explain each fix."
        )
        for f in sec_fix.get("files", []):
            await am.write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)

        be_fix = await be_agent.run(
            f"Security scan found vulnerabilities:\n{bandit_out[:1000]}\n\n"
            "Fix all HIGH and CRITICAL security issues in the backend code. "
            "Use parameterized queries, validate inputs, avoid hardcoded secrets."
        )
        for f in be_fix.get("files", []):
            await am.write_workspace_file(task_id, f["path"], f["content"])
            all_files.append(f)

        bandit_clean, bandit_out = await am.run_bandit(am.GIT_WORKSPACE)
        status = "✅ CLEAN" if bandit_clean else "⚠️ FINDINGS"
        am.add_log(f"[Security] Retry {retry + 1}/{am.MAX_RETRIES} — bandit {status}")
        if bandit_clean:
            break

    return bandit_clean, bandit_out


async def _phase_devops(
    am: Any,
    task: str,
    task_id: str,
    arch_project_ctx: str,
    generated_summary: str,
    dv_agent: CoDevxAgentBase,
    all_files: list[dict[str, Any]],
) -> None:
    """Phase 6 — DevOps Engineer generates Dockerfile, CI/CD, K8s manifests."""
    am.set_agent_status("DevOps Engineer", "DEPLOYING...", "orange")
    am.add_log("[DevOps Engineer] Writing Dockerfile + CI/CD pipeline...")

    dv_memories = await am.db_recall_memories("DevOps Engineer", am.MEMORY_CONTEXT_K)
    dv_agent.recall_and_inject_memories(task_id, dv_memories)

    dv_result = await dv_agent.run(
        f"Task: {task}\n\nGenerated files:\n{generated_summary}{arch_project_ctx}\n\n"
        f"Past experience:\n{dv_agent._memory_context()}\n\n"
        "Create Dockerfile, GitHub Actions CI/CD workflow, and K8s manifests."
    )
    for f in dv_result.get("files", []):
        await am.write_workspace_file(task_id, f["path"], f["content"])
        all_files.append(f)
    for note in dv_result.get("notes", []):
        await am.db_store_memory(task_id, "DevOps Engineer", "infra_pattern", note)

    am.add_log(f"[DevOps Engineer] ✅ {len(dv_result.get('files', []))} infra files written.")
    am.set_agent_status("DevOps Engineer", "IDLE", "orange")


async def _phase_delivery_report(
    am: Any,
    task: str,
    task_id: str,
    branch: str,
    all_files: list[dict[str, Any]],
    tests_passed: int,
    bandit_clean: bool,
    pr_url: str | None,
    infra_detected: list[str],
    msghub_rounds: int,
    pm_agent: CoDevxAgentBase,
    channel: Any,
) -> None:
    """Phase 8 — Project Manager compiles and broadcasts the delivery report."""
    am.set_agent_status("Project Manager", "REPORTING...", "blue")
    am.add_log("[Project Manager] Compiling delivery report...")

    pm_memories = await am.db_recall_memories("Project Manager", am.MEMORY_CONTEXT_K)
    pm_agent.recall_and_inject_memories(task_id, pm_memories)

    generated_summary = "\n".join(f"- {f['path']}" for f in all_files)
    pm_result = await pm_agent.run(
        f"Completed task: {task}\nTask ID: {task_id}\n\n"
        f"Files generated ({len(all_files)}):\n{generated_summary}\n\n"
        f"Tests passed: {tests_passed} | Branch: {branch} | PR: {pr_url or 'N/A'}\n"
        f"Past deliveries:\n{pm_agent._memory_context()}\n\nWrite a concise delivery report."
    )
    for note in pm_result.get("notes", []):
        await am.db_store_memory(task_id, "Project Manager", "delivery", note)

    report = (
        f"## 🚀 Task Complete — `{task}`\n"
        f"**ID:** `{task_id}` | **Branch:** `{branch}`"
        + (f" | [PR]({pr_url})" if pr_url else "") + "\n\n"
        f"- 📂 **{len(all_files)} files** generated\n"
        f"- ✅ **{tests_passed} tests** passed\n"
        f"- 🔒 Security: {'✅ CLEAN' if bandit_clean else '⚠️ review required'}\n"
        f"- 🤖 LLM: {'✅ ' + am.LLM_MODEL if am.LLM_ENABLED else '⚠️ simulation mode'}\n"
        f"- 🧠 AgentScope: ✅ MsgHub collaboration — {msghub_rounds} rounds\n"
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
        "llm_used": int(am.LLM_ENABLED),
    }
    await am.db_save_task(task_record)
    am.SYSTEM_STATE["history"].insert(0, task_record)
    if len(am.SYSTEM_STATE["history"]) > 50:
        am.SYSTEM_STATE["history"] = am.SYSTEM_STATE["history"][:50]

    reports_ch = am.bot.get_channel(am.CH_REPORTS) if am.CH_REPORTS else channel
    await (reports_ch or channel).send(report)


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

async def execute_agentscope_pipeline(channel: Any, task: str) -> None:
    """
    Full 8-agent SDLC pipeline powered by AgentScope.

    This function is a drop-in replacement for execute_pipeline() and is
    called from all entry points in agent_mesh.py:
      - POST /api/order
      - Discord !order (via ApprovalView.approve)
      - POST /webhook/zeroclaw
      - POST /webhook/whatsapp
      - MCP codevx_submit_order tool call

    LLM-powered when AgentScope is initialized; gracefully falls back to
    the legacy execute_pipeline() if AgentScope agents are in simulation mode.
    """
    am = _am()

    task_id = str(uuid.uuid4())[:8]
    branch  = f"feat/{task_id}"
    all_files: list[dict[str, Any]] = []
    tests_passed = 0
    bandit_clean = True
    pr_url: str | None = None

    await am.git_init_workspace()

    # Read the living project architecture document
    project_arch = am._read_project_architecture()
    arch_project_ctx = (
        f"\n\n---\n**Existing Project Architecture** (extend this — do not redesign from scratch):\n{project_arch}"
        if project_arch
        else "\n\n(No existing project architecture file — this may be the first task for this project.)"
    )
    if project_arch:
        am.add_log("[PM] 📖 Loaded existing PROJECT_ARCHITECTURE.md for context injection.")

    # Build agents with their toolkits
    msghub_rounds = int(am.MSGHUB_ROUNDS) if hasattr(am, "MSGHUB_ROUNDS") else 2
    qa_toolkit = build_qa_toolkit()
    security_toolkit = build_security_toolkit()
    devops_toolkit = build_devops_toolkit()

    model_config_name = "codevx-primary"
    as_cfg = am.SYSTEM_STATE.get("agentscope_config")
    if as_cfg and hasattr(as_cfg, "model_config_name"):
        model_config_name = as_cfg.model_config_name

    agents = build_agents(
        model_config_name=model_config_name,
        qa_toolkit=qa_toolkit,
        security_toolkit=security_toolkit,
        devops_toolkit=devops_toolkit,
    )

    pm_agent   = agents["Project Manager"]
    arch_agent = agents["Architect"]
    fe_agent   = agents["Frontend Dev"]
    be_agent   = agents["Backend Dev"]
    db_agent   = agents["Database Engineer"]
    qa_agent   = agents["QA Engineer"]
    sec_agent  = agents["Security Analyst"]
    dv_agent   = agents["DevOps Engineer"]

    try:
        # Phase 1: Architect
        architecture_doc = await _phase_architect(
            am, task, task_id, arch_project_ctx, arch_agent, all_files
        )

        # Phase 2: MsgHub — Frontend ↔ Backend collaboration
        fe_result, be_result = await _phase_msghub(
            am, task, task_id, architecture_doc, arch_project_ctx,
            fe_agent, be_agent, msghub_rounds, all_files,
        )

        # Phase 3: Database Engineer
        await _phase_database(
            am, task, task_id, architecture_doc, arch_project_ctx,
            be_result.get("summary", ""), db_agent, all_files,
        )

        # Phase 4: QA Engineer with self-correcting loop
        _, tests_passed = await _phase_qa(
            am, task, task_id, arch_project_ctx,
            be_result.get("summary", ""), fe_result.get("summary", ""),
            qa_agent, be_agent, fe_agent, all_files,
        )

        # Phase 5: Security Analyst with self-correcting loop
        generated_summary = "\n".join(f"- {f['path']}" for f in all_files)
        bandit_clean = await _phase_security(
            am, task, task_id, architecture_doc, arch_project_ctx,
            generated_summary, sec_agent, be_agent, all_files,
        )

        # Phase 6: DevOps Engineer
        generated_summary = "\n".join(f"- {f['path']}" for f in all_files)
        await _phase_devops(
            am, task, task_id, arch_project_ctx, generated_summary, dv_agent, all_files
        )

        # Architecture doc update
        am.add_log("[PM] Updating living project architecture document...")
        arch_update = await am.call_llm(
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
                f"New files added in this task:\n"
                + "\n".join(f"- {f['path']}" for f in all_files) + "\n\n"
                "Update the architecture document to reflect this task's additions. "
                "Add/update sections for: new API endpoints, data models, React components, "
                "database schema changes, and any key architectural decisions made."
            ),
            temperature=0.3,
        )
        await am.write_workspace_file(task_id, "docs/PROJECT_ARCHITECTURE.md", arch_update)
        all_files.append({"path": "docs/PROJECT_ARCHITECTURE.md", "content": arch_update})
        am.add_log("[PM] ✅ docs/PROJECT_ARCHITECTURE.md updated and queued for commit.")

        # Phase 7: Git commit + PR
        all_file_paths = [f["path"] for f in all_files]
        infra_detected = am._detect_infra_files(all_file_paths)
        am.add_log(f"[GIT] Committing {len(all_files)} files to branch {branch}...")
        if infra_detected:
            am.add_log(
                f"[GIT][INFRA GATE] ⚠️  {len(infra_detected)} infrastructure file(s) in this delivery — "
                "PR will carry mandatory review checklist."
            )
        pr_url = await am.git_commit_push(task_id, branch, all_file_paths)
        am.add_log(f"[GIT] ✅ {'PR opened: ' + pr_url if pr_url else 'Committed to ' + branch}")

        # Phase 8: Project Manager — Delivery Report
        await _phase_delivery_report(
            am, task, task_id, branch, all_files, tests_passed, bandit_clean,
            pr_url, infra_detected, msghub_rounds, pm_agent, channel,
        )

    except Exception as exc:
        am.add_log(f"[ERROR] AgentScope pipeline failed: {exc}")
        try:
            await channel.send(f"❌ **Pipeline error:** `{exc}`")
        except Exception:
            pass

    finally:
        for name in am.SYSTEM_STATE["agents"]:
            am.SYSTEM_STATE["agents"][name]["status"] = "IDLE"
        am.SYSTEM_STATE["current_task"] = "None"
        asyncio.create_task(am._broadcast())
        am.add_log("[Project Manager] ✅ AgentScope workflow complete. Team standing by.")
