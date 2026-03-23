"""
Patch agent_mesh.py:
  1. Add multi-provider LLM config (LLM_MODEL, ANTHROPIC_API_KEY, GOOGLE_API_KEY,
     GROQ_API_KEY, MISTRAL_API_KEY, OLLAMA_HOST, BEDROCK_*)
  2. Replace _get_openai_client() + OpenAI-only llm_call() with LiteLLM
  3. Fix consult_ide_chatbot() Antigravity path: Antigravity is an MCP IDE,
     not an API -- so "antigravity" consultation = calling Gemini via LiteLLM
  4. Remove wrong ANTIGRAVITY_API_URL assumption
"""
import sys, re

with open("agent_mesh.py", encoding="utf-8") as fh:
    text = fh.read()

# ── 1. Config: replace the static LLM block with the multi-provider block ────
OLD_CONFIG = '''# LLM (OpenAI or any OpenAI-compatible endpoint)
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")  # blank = official OpenAI'''

NEW_CONFIG = '''# ── LLM Brain ─────────────────────────────────────────────────────────────────
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
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", LLM_MODEL)'''

if OLD_CONFIG in text and "LLM_MODEL" not in text:
    text = text.replace(OLD_CONFIG, NEW_CONFIG)
    print("Step 1: multi-provider LLM config added.")
elif "LLM_MODEL" in text:
    print("Step 1: already patched, skipping.")
else:
    print("ERROR Step 1: config anchor not found.", file=sys.stderr)
    sys.exit(1)

# ── 2. Remove rogue ANTIGRAVITY_API_URL config ───────────────────────────────
# (Antigravity is an MCP IDE, not a REST API endpoint we call into)
OLD_ANTIGRAVITY_CFG = '''# Google Antigravity / Gemini Code Assist (OpenAI-compatible endpoint)
ANTIGRAVITY_API_URL = os.getenv("ANTIGRAVITY_API_URL", "")   # e.g. https://generativelanguage.googleapis.com/v1beta/openai
ANTIGRAVITY_API_KEY = os.getenv("ANTIGRAVITY_API_KEY", "")   # Google Cloud / AI Studio API key
ANTIGRAVITY_MODEL   = os.getenv("ANTIGRAVITY_MODEL", "gemini-2.0-flash")  # or gemini-2.5-pro, etc.'''

NEW_ANTIGRAVITY_CFG = '''# Antigravity IDE -- the Google AI IDE connects to CoDevx via MCP (see antigravity_mcp_config.json).
# For "consult Antigravity" in IDE_TOOLS, we call Google Gemini directly (what Antigravity runs).
# Set GOOGLE_API_KEY above and use IDE_CHATBOT=antigravity to send hints to Gemini during pipeline.
ANTIGRAVITY_MODEL = os.getenv("ANTIGRAVITY_MODEL", "gemini/gemini-2.5-pro")  # Gemini model for IDE tool consultation'''

if OLD_ANTIGRAVITY_CFG in text:
    text = text.replace(OLD_ANTIGRAVITY_CFG, NEW_ANTIGRAVITY_CFG)
    print("Step 2: Antigravity config corrected (MCP IDE, not REST API).")
else:
    print("WARN Step 2: ANTIGRAVITY_API_URL block not found -- skipping (may already be clean).")

# ── 3. Replace _get_openai_client() + llm_call() with LiteLLM ───────────────
OLD_LLM_BLOCK = '''# Shared OpenAI client — created once, reused across all agent calls
_openai_client: Any = None


def _get_openai_client() -> Any:
    """Return a lazily-initialized shared AsyncOpenAI client."""
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        _openai_client = AsyncOpenAI(**kwargs)
    return _openai_client'''

NEW_LLM_BLOCK = '''def _has_any_llm_key() -> bool:
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
    )'''

if OLD_LLM_BLOCK in text and "_has_any_llm_key" not in text:
    text = text.replace(OLD_LLM_BLOCK, NEW_LLM_BLOCK)
    print("Step 3a: replaced _get_openai_client() with _has_any_llm_key().")
else:
    if "_has_any_llm_key" in text:
        print("Step 3a: already patched, skipping.")
    else:
        print("ERROR Step 3a: _get_openai_client anchor not found.", file=sys.stderr)
        sys.exit(1)

# ── 4. Replace llm_call() body ───────────────────────────────────────────────
OLD_LLM_CALL = '''async def llm_call(agent: str, user_message: str, *, temperature: float | None = None) -> str:
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

    # ── Copilot / Cursor bridge ──────────────────────────────────────────────────────────────────────────────────────────
    if LLM_PROVIDER in ("copilot", "cursor"):
        add_log(f"[{agent}] -> Copilot Bridge ({COPILOT_BRIDGE_URL})")
        result = await _call_copilot_bridge(agent, system_prompt, user_message, temp)
        if result:
            return result
        # Bridge failed -- try OpenAI if available
        add_log(f"[{agent}] Copilot bridge unreachable, trying OpenAI fallback...")

    # ── Simulation ──────────────────────────────────────────────────────────────────────────────────────────────────────
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

    # ── OpenAI (default) ───────────────────────────────────────────────────────────────────────────────────────────────
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

NEW_LLM_CALL = '''async def llm_call(agent: str, user_message: str, *, temperature: float | None = None) -> str:
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
            f"[SIMULATED]\\n"
            f"# FILE: workspace/{slug}/main.py\\n"
            f"# {agent} placeholder for: {user_message[:120]}\\n"
            f"def placeholder(): pass\\n"
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
        return f"[LLM ERROR] {exc}"'''

if "async def llm_call" in text and "_has_any_llm_key" in text:
    # Find and replace the llm_call function - need to be careful about exact match
    # Use a simplified anchor that's unique
    CALL_ANCHOR = 'async def llm_call(agent: str, user_message: str, *, temperature: float | None = None) -> str:\n    """\n    Call the configured LLM for the given agent.\n\n    LLM_PROVIDER controls the backend:\n      openai   -- OpenAI / Azure / any compatible endpoint (default)\n      copilot  -- GitHub Copilot via codevx-vscode-bridge extension (:8001)\n      cursor   -- alias for copilot (same HTTP bridge protocol)\n      simulate -- always simulate regardless of API keys\n\n    Falls back to OpenAI if Copilot bridge is unreachable,\n    then to simulation if OPENAI_API_KEY is also unset.\n    """'

    CALL_END = '    except Exception as exc:\n        add_log(f"[{agent}] LLM error: {exc}")\n        return f"[LLM ERROR] {exc}"'

    if CALL_ANCHOR in text and CALL_END in text:
        start = text.index(CALL_ANCHOR)
        end   = text.index(CALL_END) + len(CALL_END)
        old_block = text[start:end]

        text = text[:start] + NEW_LLM_CALL + text[end:]
        print("Step 4: llm_call() replaced with LiteLLM routing.")
    else:
        print("WARN Step 4: llm_call anchors not matched precisely, trying fallback search...")
        if 'add_log(f"[{agent}] LLM error: {exc}")' in text:
            # narrow replacement via simpler regex
            import re
            pattern = r'async def llm_call\(.*?\n        return f"\[LLM ERROR\] \{exc\}"'
            if re.search(pattern, text, re.DOTALL):
                text = re.sub(pattern, NEW_LLM_CALL, text, flags=re.DOTALL)
                print("Step 4: llm_call() replaced (regex fallback).")
            else:
                print("ERROR Step 4: could not match llm_call body.")
        else:
            print("ERROR Step 4: LLM error anchor not found.")
else:
    print("INFO Step 4: llm_call not replaced (already updated or _has_any_llm_key missing).")

# ── 5. Fix consult_ide_chatbot() Antigravity path ────────────────────────────
# Remove the old OpenAI-compat Antigravity REST call, replace with LiteLLM Gemini
OLD_AG_PATH = '''        elif _ide == "antigravity":
            # Google Antigravity / Gemini Code Assist (OpenAI-compatible REST)
            if not ANTIGRAVITY_API_KEY or not ANTIGRAVITY_API_URL:
                add_log(
                    f"[{agent}] [Antigravity] skipped -- "
                    "ANTIGRAVITY_API_URL and ANTIGRAVITY_API_KEY required"
                )
                continue
            try:
                from openai import AsyncOpenAI as _AGClient
                ag = _AGClient(
                    api_key=ANTIGRAVITY_API_KEY,
                    base_url=ANTIGRAVITY_API_URL,
                )
                ag_resp = await ag.chat.completions.create(
                    model=ANTIGRAVITY_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are Google Antigravity, an AI coding assistant. "
                                f"Provide concise, actionable {topic}."
                            ),
                        },
                        {"role": "user", "content": context[:3000]},
                    ],
                    max_tokens=1200,
                    temperature=0.3,
                )
                result = ag_resp.choices[0].message.content or ""
                if result:
                    parts.append(f"### Antigravity says:\\n{result}")
                    add_log(f"[{agent}] [Antigravity] {topic}: {result[:80]}")
            except Exception as exc:
                add_log(f"[{agent}] [Antigravity] error: {exc}")'''

NEW_AG_PATH = '''        elif _ide == "antigravity":
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
                    parts.append(f"### Antigravity (Gemini) says:\\n{result}")
                    add_log(f"[{agent}] [Antigravity/Gemini] {topic}: {result[:80]}")
            except Exception as exc:
                add_log(f"[{agent}] [Antigravity/Gemini] error: {exc}")'''

if OLD_AG_PATH in text and "ANTIGRAVITY_API_KEY or not ANTIGRAVITY_API_URL" in text:
    text = text.replace(OLD_AG_PATH, NEW_AG_PATH)
    print("Step 5: Antigravity consultation path fixed (now calls Gemini via LiteLLM).")
elif "Antigravity is a Google MCP IDE" in text:
    print("Step 5: already patched, skipping.")
else:
    print("WARN Step 5: Antigravity path anchor not matched -- manual check needed.")

# ── Write ────────────────────────────────────────────────────────────────────
with open("agent_mesh.py", "w", encoding="utf-8") as fh:
    fh.write(text)

print("\nMulti-LLM patch complete.  Run: python -m py_compile agent_mesh.py")
