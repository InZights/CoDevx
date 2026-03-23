"""
Patch agent_mesh.py: add IDE chatbot tools so agents can consult
GitHub Copilot, Cursor AI, and Google Antigravity as SUPPLEMENTARY tools
during the pipeline -- separate from the main LLM brain.
"""
import sys, re

with open("agent_mesh.py", encoding="utf-8") as fh:
    text = fh.read()

# ── 1. Add IDE tool config after COPILOT_BRIDGE_URL line ────────────────────
ANCHOR_CONFIG = 'COPILOT_BRIDGE_URL = os.getenv("COPILOT_BRIDGE_URL", "http://localhost:8001")  # VS Code bridge'

NEW_CONFIG = (
    'COPILOT_BRIDGE_URL = os.getenv("COPILOT_BRIDGE_URL", "http://localhost:8001")  # VS Code bridge\n'
    '\n'
    '# IDE Chatbot Tools -- agents consult IDE chatbots as SUPPLEMENTARY specialists\n'
    '# This is independent of LLM_PROVIDER (the brain); these are additional consultants.\n'
    '# Set IDE_TOOLS_ENABLED=true and at least one IDE source to activate.\n'
    'IDE_TOOLS_ENABLED   = os.getenv("IDE_TOOLS_ENABLED", "false").lower() == "true"\n'
    'IDE_CHATBOT         = os.getenv("IDE_CHATBOT", "copilot")  # copilot | cursor | antigravity | all\n'
    '# Google Antigravity / Gemini Code Assist (OpenAI-compatible endpoint)\n'
    'ANTIGRAVITY_API_URL = os.getenv("ANTIGRAVITY_API_URL", "")   # e.g. https://generativelanguage.googleapis.com/v1beta/openai\n'
    'ANTIGRAVITY_API_KEY = os.getenv("ANTIGRAVITY_API_KEY", "")   # Google Cloud / AI Studio API key\n'
    'ANTIGRAVITY_MODEL   = os.getenv("ANTIGRAVITY_MODEL", "gemini-2.0-flash")  # or gemini-2.5-pro, etc.\n'
)

if ANCHOR_CONFIG in text and "IDE_TOOLS_ENABLED" not in text:
    text = text.replace(ANCHOR_CONFIG, NEW_CONFIG)
    print("Step 1: IDE tool config added.")
else:
    if "IDE_TOOLS_ENABLED" in text:
        print("Step 1: already patched, skipping.")
    else:
        print("ERROR Step 1: anchor not found.", file=sys.stderr); sys.exit(1)

# ── 2. Add consult_ide_chatbot() function before execute_pipeline ────────────
ANCHOR_FN = 'async def execute_pipeline(channel: Any, task: str) -> None:'

NEW_FN = (
    '# ============================================================\n'
    '# 6.  IDE CHATBOT TOOLS  (Copilot / Cursor / Antigravity)\n'
    '# ============================================================\n'
    '\n'
    'async def consult_ide_chatbot(\n'
    '    agent: str,\n'
    '    topic: str,\n'
    '    context: str,\n'
    '    *,\n'
    '    ide: str | None = None,\n'
    ') -> str:\n'
    '    """\n'
    '    Let an agent consult an IDE chatbot (GitHub Copilot, Cursor AI, or\n'
    '    Google Antigravity) as a SUPPLEMENTARY TOOL -- separate from the\n'
    '    agent\'s main LLM brain (LLM_PROVIDER).\n'
    '\n'
    '    `topic`   -- short label, e.g. "code review", "test suggestions"\n'
    '    `context` -- the code / question to send to the IDE chatbot\n'
    '    `ide`     -- "copilot" | "cursor" | "antigravity" | "all"\n'
    '                 defaults to the IDE_CHATBOT env setting.\n'
    '\n'
    '    Returns combined IDE chatbot response, or empty string if unavailable.\n'
    '    """\n'
    '    if not IDE_TOOLS_ENABLED:\n'
    '        return ""\n'
    '\n'
    '    target = ide or IDE_CHATBOT\n'
    '    ides   = ["copilot", "cursor", "antigravity"] if target == "all" else [target]\n'
    '    parts: list[str] = []\n'
    '\n'
    '    for _ide in ides:\n'
    '        if _ide in ("copilot", "cursor"):\n'
    '            # Route through the VS Code extension bridge (:8001)\n'
    '            payload = {\n'
    '                "agent": agent,\n'
    '                "system": (\n'
    '                    f"You are the {_ide.title()} AI assistant integrated into "\n'
    '                    f"an autonomous software development pipeline. "\n'
    '                    f"Provide concise, actionable {topic}."\n'
    '                ),\n'
    '                "user": context[:3000],\n'
    '                "ide": _ide,\n'
    '            }\n'
    '            try:\n'
    '                import httpx\n'
    '                async with httpx.AsyncClient(timeout=120.0) as client:\n'
    '                    resp = await client.post(\n'
    '                        f"{COPILOT_BRIDGE_URL}/chat", json=payload\n'
    '                    )\n'
    '                    resp.raise_for_status()\n'
    '                    result = resp.json().get("content", "")\n'
    '                    if result:\n'
    '                        parts.append(f"### {_ide.title()} says:\\n{result}")\n'
    '                        add_log(f"[{agent}] [{_ide.title()}] {topic}: {result[:80]}")\n'
    '            except Exception as exc:\n'
    '                add_log(f"[{agent}] [{_ide.title()}] bridge unreachable: {exc}")\n'
    '\n'
    '        elif _ide == "antigravity":\n'
    '            # Google Antigravity / Gemini Code Assist (OpenAI-compatible REST)\n'
    '            if not ANTIGRAVITY_API_KEY or not ANTIGRAVITY_API_URL:\n'
    '                add_log(\n'
    '                    f"[{agent}] [Antigravity] skipped -- "\n'
    '                    "ANTIGRAVITY_API_URL and ANTIGRAVITY_API_KEY required"\n'
    '                )\n'
    '                continue\n'
    '            try:\n'
    '                from openai import AsyncOpenAI as _AGClient\n'
    '                ag = _AGClient(\n'
    '                    api_key=ANTIGRAVITY_API_KEY,\n'
    '                    base_url=ANTIGRAVITY_API_URL,\n'
    '                )\n'
    '                ag_resp = await ag.chat.completions.create(\n'
    '                    model=ANTIGRAVITY_MODEL,\n'
    '                    messages=[\n'
    '                        {\n'
    '                            "role": "system",\n'
    '                            "content": (\n'
    '                                "You are Google Antigravity, an AI coding assistant. "\n'
    '                                f"Provide concise, actionable {topic}."\n'
    '                            ),\n'
    '                        },\n'
    '                        {"role": "user", "content": context[:3000]},\n'
    '                    ],\n'
    '                    max_tokens=1200,\n'
    '                    temperature=0.3,\n'
    '                )\n'
    '                result = ag_resp.choices[0].message.content or ""\n'
    '                if result:\n'
    '                    parts.append(f"### Antigravity says:\\n{result}")\n'
    '                    add_log(f"[{agent}] [Antigravity] {topic}: {result[:80]}")\n'
    '            except Exception as exc:\n'
    '                add_log(f"[{agent}] [Antigravity] error: {exc}")\n'
    '\n'
    '    return "\\n\\n".join(parts)\n'
    '\n'
    '\n'
    'async def execute_pipeline(channel: Any, task: str) -> None:\n'
)

if ANCHOR_FN in text and "consult_ide_chatbot" not in text:
    text = text.replace(ANCHOR_FN, NEW_FN)
    print("Step 2: consult_ide_chatbot() added.")
else:
    if "consult_ide_chatbot" in text:
        print("Step 2: already patched, skipping.")
    else:
        print("ERROR Step 2: anchor not found.", file=sys.stderr); sys.exit(1)

# ── 3. Wire IDE consultation into the pipeline ───────────────────────────────
# After backend + frontend phase code is written, insert a consultation block.

ANCHOR_PIPELINE = (
    '            add_log(f"[Backend Dev]  {len(be_files)} file(s) written \u2014 {ph_label}")\n'
    '            # Syntax-validate generated Python files immediately\n'
    '            syn_errors = await _validate_python_files(be_files)'
)

NEW_PIPELINE = (
    '            add_log(f"[Backend Dev]  {len(be_files)} file(s) written \u2014 {ph_label}")\n'
    '\n'
    '            # IDE Chatbot: Backend code review (runs only when IDE_TOOLS_ENABLED=true)\n'
    '            if IDE_TOOLS_ENABLED and be_phase.strip():\n'
    '                ide_review = await consult_ide_chatbot(\n'
    '                    "Backend Dev",\n'
    '                    "code review and improvement suggestions",\n'
    '                    f"Review this backend code for quality, patterns, and best practices:\\n\\n{be_phase[:2500]}",\n'
    '                )\n'
    '                if ide_review:\n'
    '                    ctx["ide_be_review"] = ide_review\n'
    '                    add_log(f"[Backend Dev] IDE review stored \u2014 {ph_label}")\n'
    '            if IDE_TOOLS_ENABLED and fe_phase.strip():\n'
    '                ide_fe_review = await consult_ide_chatbot(\n'
    '                    "Frontend Dev",\n'
    '                    "UI/UX code review and accessibility suggestions",\n'
    '                    f"Review this frontend code for quality, accessibility (WCAG 2.1 AA), and patterns:\\n\\n{fe_phase[:2000]}",\n'
    '                )\n'
    '                if ide_fe_review:\n'
    '                    ctx["ide_fe_review"] = ide_fe_review\n'
    '                    add_log(f"[Frontend Dev] IDE review stored \u2014 {ph_label}")\n'
    '\n'
    '            # Syntax-validate generated Python files immediately\n'
    '            syn_errors = await _validate_python_files(be_files)'
)

if ANCHOR_PIPELINE in text and "ide_be_review" not in text:
    text = text.replace(ANCHOR_PIPELINE, NEW_PIPELINE)
    print("Step 3a: Backend/Frontend IDE consultation wired in.")
else:
    if "ide_be_review" in text:
        print("Step 3a: already patched, skipping.")
    else:
        print("WARN Step 3a: anchor not found -- pipeline injection skipped.")

# ── 3b. Wire IDE consultation into QA phase ──────────────────────────────────
ANCHOR_QA = (
    '            qa_out  = await llm_call("QA Engineer", qa_ctx)\n'
)

NEW_QA = (
    '            # IDE Chatbot: ask for additional test case suggestions before writing tests\n'
    '            if IDE_TOOLS_ENABLED and be_phase.strip():\n'
    '                ide_test_hints = await consult_ide_chatbot(\n'
    '                    "QA Engineer",\n'
    '                    "test case suggestions (edge cases, error paths, security tests)",\n'
    '                    f"Suggest additional test cases for this code:\\n\\n{be_phase[:2000]}",\n'
    '                )\n'
    '                if ide_test_hints:\n'
    '                    qa_ctx += f"\\n\\nIDE chatbot test suggestions:\\n{ide_test_hints[:800]}"\n'
    '                    add_log("[QA Engineer] IDE test hints incorporated.")\n'
    '\n'
    '            qa_out  = await llm_call("QA Engineer", qa_ctx)\n'
)

if ANCHOR_QA in text and "ide_test_hints" not in text:
    text = text.replace(ANCHOR_QA, NEW_QA)
    print("Step 3b: QA IDE consultation wired in.")
else:
    if "ide_test_hints" in text:
        print("Step 3b: already patched, skipping.")
    else:
        print("WARN Step 3b: QA anchor not found -- skipping.")

# ── 3c. Wire IDE consultation into Security phase ────────────────────────────
ANCHOR_SEC = (
    '            sec_out     = await llm_call("Security Analyst", sec_ctx)\n'
)

NEW_SEC = (
    '            # IDE Chatbot: get security vulnerability hints before LLM scan\n'
    '            if IDE_TOOLS_ENABLED and be_phase.strip():\n'
    '                ide_sec_hints = await consult_ide_chatbot(\n'
    '                    "Security Analyst",\n'
    '                    "security vulnerability analysis (OWASP Top 10, injection, auth flaws)",\n'
    '                    f"Identify security vulnerabilities in this backend code:\\n\\n{be_phase[:2000]}",\n'
    '                )\n'
    '                if ide_sec_hints:\n'
    '                    sec_ctx += f"\\n\\nIDE chatbot security hints:\\n{ide_sec_hints[:800]}"\n'
    '                    add_log("[Security Analyst] IDE security hints incorporated.")\n'
    '\n'
    '            sec_out     = await llm_call("Security Analyst", sec_ctx)\n'
)

if ANCHOR_SEC in text and "ide_sec_hints" not in text:
    text = text.replace(ANCHOR_SEC, NEW_SEC)
    print("Step 3c: Security IDE consultation wired in.")
else:
    if "ide_sec_hints" in text:
        print("Step 3c: already patched, skipping.")
    else:
        print("WARN Step 3c: Security anchor not found -- skipping.")

# ── 3d. Wire IDE consultation into Architect phase ───────────────────────────
ANCHOR_ARCH = (
    '        arch_out = await llm_call("Architect", arch_prompt)\n'
    '        ctx["arch"] = arch_out\n'
)

NEW_ARCH = (
    '        arch_out = await llm_call("Architect", arch_prompt)\n'
    '        # IDE Chatbot: second opinion on the architecture design\n'
    '        if IDE_TOOLS_ENABLED:\n'
    '            ide_arch_review = await consult_ide_chatbot(\n'
    '                "Architect",\n'
    '                "architecture review (scalability, maintainability, design patterns)",\n'
    '                f"Review this software architecture plan and suggest improvements:\\n\\n{arch_out[:2500]}",\n'
    '            )\n'
    '            if ide_arch_review:\n'
    '                arch_out += f"\\n\\n<!-- IDE Architecture Review -->\\n{ide_arch_review[:600]}"\n'
    '                add_log("[Architect] IDE architecture review appended.")\n'
    '        ctx["arch"] = arch_out\n'
)

if ANCHOR_ARCH in text and "ide_arch_review" not in text:
    text = text.replace(ANCHOR_ARCH, NEW_ARCH)
    print("Step 3d: Architect IDE consultation wired in.")
else:
    if "ide_arch_review" in text:
        print("Step 3d: already patched, skipping.")
    else:
        print("WARN Step 3d: Architect anchor not found -- skipping.")

# ── Write ────────────────────────────────────────────────────────────────────
with open("agent_mesh.py", "w", encoding="utf-8") as fh:
    fh.write(text)

print("\nIDE Tools patch complete. Run: python -m py_compile agent_mesh.py")
