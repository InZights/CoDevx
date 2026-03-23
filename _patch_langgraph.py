"""
Patch script: Add LangGraph implementation to agent_mesh.py
============================================================
Changes:
  1. requirements.txt  — add langgraph>=0.2.0
  2. agent_mesh.py
     A. Config  — LANGGRAPH_ENABLED, HUMAN_GATE_ENABLED, HUMAN_GATE_TIMEOUT
     B. State   — _pipeline_gates, _gate_task_map
     C. Discord — ArchGateView class (architecture approval buttons)
     D. Helpers — _notify_manager_gate(), _run_qa_subgraph(), _run_security_subgraph()
     E. execute_pipeline() — HITL gate after Architect, LangGraph QA+Security dispatch
     F. WhatsApp webhook — "approve arch / reject arch" commands
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MESH = ROOT / "agent_mesh.py"
REQS = ROOT / "requirements.txt"


def patch_requirements() -> None:
    txt = REQS.read_text(encoding="utf-8")
    if "langgraph" in txt:
        print("[requirements] langgraph already present — skipping")
        return
    txt = txt.rstrip() + "\nlanggraph>=0.2.0\n"
    REQS.write_text(txt, encoding="utf-8")
    print("[requirements] Added langgraph>=0.2.0")


def patch_mesh() -> None:
    src = MESH.read_text(encoding="utf-8")
    original_len = len(src.splitlines())

    # ── A. Config vars ────────────────────────────────────────────────────────
    ANCHOR_CONFIG = "MEMORY_CONTEXT_K  = int(os.getenv(\"MEMORY_CONTEXT_K\", \"5\"))       # past memories to inject"
    INSERT_CONFIG = """\nMEMORY_CONTEXT_K  = int(os.getenv("MEMORY_CONTEXT_K", "5"))       # past memories to inject

# ── LangGraph ─────────────────────────────────────────────────────────────────
# Set LANGGRAPH_ENABLED=true to use LangGraph ReAct subgraphs for QA and
# Security gates (true autonomous reasoning loops + SQLite checkpointing).
# Set HUMAN_GATE_ENABLED=true to pause after Architect and notify the manager
# via Discord (#plans channel button) and/or WhatsApp before coding begins.
LANGGRAPH_ENABLED  = os.getenv("LANGGRAPH_ENABLED",  "false").lower() == "true"
HUMAN_GATE_ENABLED = os.getenv("HUMAN_GATE_ENABLED", "false").lower() == "true"
HUMAN_GATE_TIMEOUT = int(os.getenv("HUMAN_GATE_TIMEOUT", "300"))  # seconds"""

    if "LANGGRAPH_ENABLED" in src:
        print("[config] LANGGRAPH_ENABLED already present — skipping")
    else:
        src = src.replace(ANCHOR_CONFIG, INSERT_CONFIG)
        print("[config] Added LANGGRAPH_ENABLED / HUMAN_GATE_ENABLED / HUMAN_GATE_TIMEOUT")

    # ── B. Shared-state: gate dicts ───────────────────────────────────────────
    ANCHOR_STATE = '_zc_pending: dict[str, tuple[str, str]] = {}           # ZeroClaw sender -> (task, reply_url)'
    INSERT_STATE = """_zc_pending: dict[str, tuple[str, str]] = {}           # ZeroClaw sender -> (task, reply_url)
_pipeline_gates: dict[str, asyncio.Event] = {}  # task_id -> Event (human-in-the-loop gate)
_gate_task_map:  dict[str, str]           = {}  # "current" -> task_id (WhatsApp shortcut)"""

    if "_pipeline_gates" in src:
        print("[state] _pipeline_gates already present — skipping")
    else:
        src = src.replace(ANCHOR_STATE, INSERT_STATE)
        print("[state] Added _pipeline_gates + _gate_task_map")

    # ── C. ArchGateView Discord class ─────────────────────────────────────────
    ARCH_GATE_VIEW = '''

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
'''

    # Insert right before "# ============================================================\n# 9. EXECUTION PIPELINE"
    ANCHOR_EXEC_SECTION = "# ============================================================\n# 9. EXECUTION PIPELINE"
    if "ArchGateView" in src:
        print("[discord] ArchGateView already present — skipping")
    else:
        src = src.replace(ANCHOR_EXEC_SECTION, ARCH_GATE_VIEW + "\n" + ANCHOR_EXEC_SECTION)
        print("[discord] Added ArchGateView")

    # ── D. Helper functions / LangGraph subgraphs ────────────────────────────
    LANGGRAPH_HELPERS = '''

# ============================================================
# 9.1  LANGGRAPH SUBGRAPHS  (QA + Security ReAct loops)
# ============================================================

async def _notify_manager_gate(task_id: str, task: str, arch_summary: str) -> None:
    """Notify Discord (#plans) and WhatsApp with arch design + approval buttons."""
    preview = arch_summary[:1200].strip()
    discord_msg = (
        f"🏗️ **Architecture Ready — `{task_id}`**\\n\\n"
        f"**Task:** {task}\\n\\n"
        f"**Design:**\\n{preview}\\n\\n"
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
            f"Architecture ready — task {task_id}\\n\\n"
            f"Task: {task}\\n\\n"
            f"{arch_summary[:600]}\\n\\n"
            f"Reply:\\n"
            f"  approve arch {task_id}  — proceed with coding\\n"
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
            "Task: " + task + "\\n\\n"
            "Architecture summary:\\n" + arch_out[:1200] + "\\n\\n"
            "Generated files manifest:\\n" + _build_file_manifest(all_files) + "\\n\\n"
            "Frontend code (latest phase):\\n" + fe_phase[:1500] + "\\n\\n"
            "Backend code (latest phase):\\n" + be_phase[:1500]
        )
        if attempt > 0 and test_output:
            qa_ctx += "\\n\\nTest failures to fix:\\n" + test_output[:600]
        if IDE_TOOLS_ENABLED and be_phase.strip():
            ide_hints = await consult_ide_chatbot(
                "QA Engineer",
                "test case suggestions (edge cases, error paths, security tests)",
                f"Suggest additional test cases for this code:\\n\\n{be_phase[:2000]}",
            )
            if ide_hints:
                qa_ctx += f"\\n\\nIDE chatbot test suggestions:\\n{ide_hints[:800]}"
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
            "Review for OWASP Top 10 + OWASP ASVS Level 2 + CWE Top 25:\\n\\n"
            "Generated files:\\n" + _build_file_manifest(all_files) + "\\n\\n"
            "Backend code (full latest phase):\\n" + be_phase[:2000] + "\\n\\n"
            "Frontend code (full latest phase):\\n" + fe_phase[:1000] + "\\n\\n"
            "Database schema:\\n" + db_cumulative[-400:]
        )
        if attempt > 0 and prev_findings:
            sec_ctx += "\\n\\nPrevious scan findings:\\n" + prev_findings[:500]
        if IDE_TOOLS_ENABLED and be_phase.strip():
            ide_hints = await consult_ide_chatbot(
                "Security Analyst",
                "security vulnerability analysis (OWASP Top 10, injection, auth flaws)",
                f"Identify security vulnerabilities in this backend code:\\n\\n{be_phase[:2000]}",
            )
            if ide_hints:
                sec_ctx += f"\\n\\nIDE chatbot security hints:\\n{ide_hints[:800]}"
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
'''

    ANCHOR_EXEC_PIPELINE = "async def execute_pipeline(channel: Any, task: str) -> None:"
    if "_run_qa_subgraph" in src:
        print("[subgraphs] LangGraph subgraphs already present — skipping")
    else:
        src = src.replace(ANCHOR_EXEC_PIPELINE, LANGGRAPH_HELPERS + "\n\n" + ANCHOR_EXEC_PIPELINE)
        print("[subgraphs] Added _notify_manager_gate, _run_qa_subgraph, _run_security_subgraph")

    # ── E. HITL gate inside execute_pipeline (after Architect) ───────────────
    ANCHOR_PHASE_LOOP = '''        ctx["arch"] = arch_out
        add_log(f"[Architect] {arch_out.splitlines()[0][:120]}")
        add_log("[Architect] Architecture complete.")
        set_agent_status("Architect", "IDLE", "purple")

        # ── Break task into implementation phases'''

    INSERT_PHASE_LOOP = '''        ctx["arch"] = arch_out
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

        # ── Break task into implementation phases'''

    if "HUMAN_GATE_ENABLED" in src and "gate_event = asyncio.Event()" in src:
        print("[pipeline] HITL gate already wired — skipping")
    else:
        if ANCHOR_PHASE_LOOP in src:
            src = src.replace(ANCHOR_PHASE_LOOP, INSERT_PHASE_LOOP)
            print("[pipeline] Inserted HITL gate after Architect")
        else:
            print("[pipeline] WARNING — could not find Architect-end anchor; HITL gate NOT inserted")

    # ── E2. Replace QA loop with subgraph dispatch ────────────────────────────
    OLD_QA = '''        # QA GATE — test all generated files + retry loop
        for qa_attempt in range(MAX_RETRIES + 1):
            set_agent_status("QA Engineer", "TESTING...", "yellow")
            retry_lbl = f" (retry {qa_attempt}/{MAX_RETRIES})" if qa_attempt else ""
            add_log(f"[QA Engineer] Writing test suites{retry_lbl}...")

            qa_ctx = (
                "Task: " + task + "\\n\\n"
                "Architecture summary:\\n" + arch_out[:1200] + "\\n\\n"
                "Generated files manifest:\\n" + _build_file_manifest(all_files) + "\\n\\n"
                "Frontend code (latest phase):\\n" + fe_phase[:1500] + "\\n\\n"
                "Backend code (latest phase):\\n" + be_phase[:1500]
            )
            if qa_attempt > 0 and ctx.get("test_output"):
                qa_ctx += "\\n\\nTest failures to fix:\\n" + ctx["test_output"][:600]

            # IDE Chatbot: ask for additional test case suggestions before writing tests
            if IDE_TOOLS_ENABLED and be_phase.strip():
                ide_test_hints = await consult_ide_chatbot(
                    "QA Engineer",
                    "test case suggestions (edge cases, error paths, security tests)",
                    f"Suggest additional test cases for this code:\\n\\n{be_phase[:2000]}",
                )
                if ide_test_hints:
                    qa_ctx += f"\\n\\nIDE chatbot test suggestions:\\n{ide_test_hints[:800]}"
                    add_log("[QA Engineer] IDE test hints incorporated.")

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

        set_agent_status("QA Engineer", "IDLE", "yellow")'''

    NEW_QA = '''        # QA GATE — LangGraph ReAct subgraph (LANGGRAPH_ENABLED=true)
        #           or legacy retry loop (LANGGRAPH_ENABLED=false, default)
        _qa_result = await _run_qa_subgraph(
            task=task, arch_out=arch_out, fe_phase=fe_phase, be_phase=be_phase,
            all_files=all_files, qa_files=qa_files, ctx=ctx, task_id=task_id,
        )
        all_files = _qa_result["all_files"]
        qa_files  = _qa_result["qa_files"]
        ctx       = _qa_result["ctx"]'''

    if "_run_qa_subgraph" in src and NEW_QA.strip() in src:
        print("[pipeline] QA dispatch already present — skipping")
    elif OLD_QA in src:
        src = src.replace(OLD_QA, NEW_QA)
        print("[pipeline] Replaced QA for-loop with _run_qa_subgraph dispatch")
    else:
        # Try to find a close match with different spacing/encoding
        print("[pipeline] WARNING — could not find exact QA loop text; trying regex approach")
        # Use regex to find and replace the QA GATE block
        pattern = r'(        # QA GATE.*?set_agent_status\("QA Engineer", "IDLE", "yellow"\))'
        match = re.search(pattern, src, re.DOTALL)
        if match:
            src = src[:match.start()] + NEW_QA + src[match.end():]
            print("[pipeline] QA loop replaced via regex")
        else:
            print("[pipeline] CRITICAL WARNING — QA loop NOT replaced; manual edit required")

    # ── E3. Replace Security loop with subgraph dispatch ─────────────────────
    OLD_SEC = '''        # SECURITY GATE — full codebase review + tool scan + fix loop
        for sec_attempt in range(MAX_RETRIES + 1):
            set_agent_status("Security Analyst", "SCANNING...", "red")
            retry_lbl = f" (retry {sec_attempt}/{MAX_RETRIES})" if sec_attempt else ""
            add_log(f"[Security Analyst] OWASP Top 10 review{retry_lbl}...")

            sec_ctx = (
                "Review for OWASP Top 10 + OWASP ASVS Level 2 + CWE Top 25:\\n\\n"
                "Generated files:\\n" + _build_file_manifest(all_files) + "\\n\\n"
                "Backend code (full latest phase):\\n" + be_phase[:2000] + "\\n\\n"
                "Frontend code (full latest phase):\\n" + fe_phase[:1000] + "\\n\\n"
                "Database schema:\\n" + db_cumulative[-400:]
            )
            if sec_attempt > 0 and ctx.get("scan_output"):
                sec_ctx += "\\n\\nPrevious scan findings:\\n" + ctx["scan_output"][:500]

            # IDE Chatbot: get security vulnerability hints before LLM scan
            if IDE_TOOLS_ENABLED and be_phase.strip():
                ide_sec_hints = await consult_ide_chatbot(
                    "Security Analyst",
                    "security vulnerability analysis (OWASP Top 10, injection, auth flaws)",
                    f"Identify security vulnerabilities in this backend code:\\n\\n{be_phase[:2000]}",
                )
                if ide_sec_hints:
                    sec_ctx += f"\\n\\nIDE chatbot security hints:\\n{ide_sec_hints[:800]}"
                    add_log("[Security Analyst] IDE security hints incorporated.")

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
            be_out += "\\n" + sec_out   # update context for next attempt

        set_agent_status("Security Analyst", "IDLE", "red")'''

    NEW_SEC = '''        # SECURITY GATE — LangGraph ReAct subgraph (LANGGRAPH_ENABLED=true)
        #                or legacy retry loop (LANGGRAPH_ENABLED=false, default)
        _sec_result = await _run_security_subgraph(
            task=task, arch_out=arch_out, fe_phase=fe_phase, be_phase=be_phase,
            db_cumulative=db_cumulative, all_files=all_files, ctx=ctx, task_id=task_id,
        )
        all_files   = _sec_result["all_files"]
        ctx         = _sec_result["ctx"]
        scan_passed = _sec_result["scan_passed"]'''

    if "_run_security_subgraph" in src and NEW_SEC.strip() in src:
        print("[pipeline] Security dispatch already present — skipping")
    elif OLD_SEC in src:
        src = src.replace(OLD_SEC, NEW_SEC)
        print("[pipeline] Replaced Security for-loop with _run_security_subgraph dispatch")
    else:
        print("[pipeline] WARNING — could not find exact Security loop; trying regex")
        pattern = r'(        # SECURITY GATE.*?set_agent_status\("Security Analyst", "IDLE", "red"\))'
        match = re.search(pattern, src, re.DOTALL)
        if match:
            src = src[:match.start()] + NEW_SEC + src[match.end():]
            print("[pipeline] Security loop replaced via regex")
        else:
            print("[pipeline] CRITICAL WARNING — Security loop NOT replaced; manual edit required")

    # ── F. WhatsApp webhook — approve/reject arch commands ────────────────────
    ANCHOR_WA = '''    elif body_lower == "reject":
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
            "AI Dev Team Commands:\\n\\n"
            "order <task> -- start a new pipeline\\n"
            "approve -- approve the pending plan\\n"
            "reject -- reject the pending plan",
        )'''

    INSERT_WA = '''    elif body_lower == "reject":
        task = _wa_pending.pop(sender, None)
        if task:
            add_log(f"[WhatsApp] Plan rejected by {sender}")
            set_agent_status("Project Manager", "IDLE", "blue")
            SYSTEM_STATE["current_task"] = "None"
            await wa_send(sender, "Plan rejected. Send 'order <task>' to start a new one.")
        else:
            await wa_send(sender, "No pending plan to reject.")

    elif body_lower.startswith("approve arch") or body_lower.startswith("reject arch"):
        # Human-in-the-loop architecture gate commands
        parts     = Body.strip().split()
        action_wa = parts[0].lower()               # "approve" or "reject"
        tid_arg   = parts[2] if len(parts) > 2 else _gate_task_map.get("current", "")
        gate = _pipeline_gates.get(tid_arg)
        if gate and not gate.is_set():
            if action_wa == "approve":
                gate.set()
                await wa_send(sender, f"✅ Architecture approved for task {tid_arg}. Coding begins...")
                add_log(f"[HITL][WhatsApp] Architecture approved by {sender} for task {tid_arg}")
            else:
                SYSTEM_STATE[f"_gate_rejected_{tid_arg}"] = True
                gate.set()
                await wa_send(sender, f"❌ Architecture rejected for task {tid_arg}. Pipeline aborted.")
                add_log(f"[HITL][WhatsApp] Architecture rejected by {sender} for task {tid_arg}")
        else:
            await wa_send(sender, f"⚠️ No open architecture gate for task '{tid_arg}'.")

    else:
        await wa_send(
            sender,
            "AI Dev Team Commands:\\n\\n"
            "order <task>              -- start a new pipeline\\n"
            "approve                   -- approve the pending plan\\n"
            "reject                    -- reject the pending plan\\n"
            "approve arch <task_id>    -- approve architecture (HITL gate)\\n"
            "reject arch <task_id>     -- reject architecture (HITL gate)",
        )'''

    if "approve arch" in src and "_gate_task_map" in src and "HITL" in src:
        print("[whatsapp] arch gate commands already wired — skipping")
    elif ANCHOR_WA in src:
        src = src.replace(ANCHOR_WA, INSERT_WA)
        print("[whatsapp] Added 'approve/reject arch' commands to WhatsApp webhook")
    else:
        print("[whatsapp] WARNING — WhatsApp webhook anchor not found; commands NOT added")

    # ── Validate and write ────────────────────────────────────────────────────
    new_len = len(src.splitlines())
    print(f"\n[info] Line count: {original_len} → {new_len} (+{new_len - original_len})")
    MESH.write_text(src, encoding="utf-8")
    print(f"[info] Wrote {MESH}")


if __name__ == "__main__":
    patch_requirements()
    patch_mesh()
    print("\n✅ Patch complete. Run: python -m py_compile agent_mesh.py")
