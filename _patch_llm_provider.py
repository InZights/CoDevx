"""Patch agent_mesh.py: add LLM_PROVIDER + Copilot bridge routing."""
import pathlib, re

p = pathlib.Path("agent_mesh.py")
text = p.read_text(encoding="utf-8")

# ── 1. Add LLM_PROVIDER config after OPENAI_MAX_TOKENS line ─────────────────
OLD_CFG = 'OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))   # tokens per agent call'
NEW_CFG = (
    'OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))   # tokens per agent call\n'
    '\n'
    '# IDE Copilot Bridge (LLM_PROVIDER=copilot routes agent calls through GitHub Copilot/Cursor)\n'
    '# Providers: openai | copilot | cursor | simulate\n'
    'LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "openai")  # default: OpenAI API\n'
    'COPILOT_BRIDGE_URL = os.getenv("COPILOT_BRIDGE_URL", "http://localhost:8001")  # VS Code bridge'
)
assert OLD_CFG in text, "Config anchor not found"
text = text.replace(OLD_CFG, NEW_CFG, 1)

# ── 2. Add _call_copilot_bridge() helper + update llm_call() ────────────────
OLD_LLM = '''async def llm_call(agent: str, user_message: str, *, temperature: float | None = None) -> str:
    """
    Call the configured LLM for the given agent.
    Uses per-agent temperature from AGENT_TEMPERATURES unless overridden.
    Falls back to simulation if OPENAI_API_KEY is not set.
    """
    if not OPENAI_API_KEY:
        add_log(f"[{agent}] Simulating (set OPENAI_API_KEY for real LLM).")
        await asyncio.sleep(0.2)
        slug = agent.lower().replace(" ", "_")
        return (
            f"[SIMULATED \xe2\x80\x94 no OPENAI_API_KEY]\\n"
            f"# FILE: workspace/{slug}/main.py\\n"
            f"# {agent} placeholder for: {user_message[:120]}\\n"
            f"def placeholder(): pass  # replace with real LLM output\\n"
        )
    temp = temperature if temperature is not None else AGENT_TEMPERATURES.get(agent, 0.2)
    try:
        client = _get_openai_client()
        add_log(f"[{agent}] \xe2\x86\x92 {OPENAI_MODEL} (temp={temp})")
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPTS.get(agent, "You are a helpful AI.")},
                {"role": "user",   "content": user_message},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=temp,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        add_log(f"[{agent}] LLM error: {exc}")
        return f"[LLM ERROR] {exc}"'''

NEW_LLM = '''async def _call_copilot_bridge(agent: str, system: str, user: str, temperature: float) -> str:
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
    Call the configured LLM for the given agent.

    LLM_PROVIDER controls the backend:
      openai   -- OpenAI / Azure / any compatible endpoint (default)
      copilot  -- GitHub Copilot via codevx-vscode-bridge extension (:8001)
      cursor   -- alias for copilot (same HTTP bridge protocol)
      simulate -- always simulate regardless of API keys

    Falls back to OpenAI if Copilot bridge is unreachable,
    then to simulation if OPENAI_API_KEY is also unset.
    """
    temp = temperature if temperature is not None else AGENT_TEMPERATURES.get(agent, 0.2)
    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent, "You are a helpful AI.")

    # ── Copilot / Cursor bridge ──────────────────────────────────────────────
    if LLM_PROVIDER in ("copilot", "cursor"):
        add_log(f"[{agent}] -> Copilot Bridge ({COPILOT_BRIDGE_URL})")
        result = await _call_copilot_bridge(agent, system_prompt, user_message, temp)
        if result:
            return result
        # Bridge failed -- try OpenAI if available
        add_log(f"[{agent}] Copilot bridge unreachable, trying OpenAI fallback...")

    # ── Simulation ───────────────────────────────────────────────────────────
    if LLM_PROVIDER == "simulate" or not OPENAI_API_KEY:
        add_log(f"[{agent}] Simulating (LLM_PROVIDER={LLM_PROVIDER}, no OPENAI_API_KEY).")
        await asyncio.sleep(0.2)
        slug = agent.lower().replace(" ", "_")
        return (
            f"[SIMULATED]\\n"
            f"# FILE: workspace/{slug}/main.py\\n"
            f"# {agent} placeholder for: {user_message[:120]}\\n"
            f"def placeholder(): pass\\n"
        )

    # ── OpenAI (default) ─────────────────────────────────────────────────────
    try:
        client = _get_openai_client()
        add_log(f"[{agent}] -> {OPENAI_MODEL} (temp={temp})")
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=temp,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        add_log(f"[{agent}] LLM error: {exc}")
        return f"[LLM ERROR] {exc}"'''

if "_call_copilot_bridge" not in text:
    # Find and replace the llm_call function block
    # Use a simpler anchor-based split to avoid regex issues with special chars
    split_marker = "async def llm_call("
    before, remainder = text.split(split_marker, 1)
    # Find the end of the function by locating the next top-level def/class
    # after the function body ends
    end_marker = "\n\ndef parse_files_from_llm"
    func_body, after = remainder.split(end_marker, 1)
    text = before + NEW_LLM + end_marker + after
    print("LLM_PROVIDER routing patched.")
else:
    print("Already patched, skipping.")

p.write_text(text, encoding="utf-8")
print("Done.")
