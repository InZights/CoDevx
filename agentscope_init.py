"""
agentscope_init.py — AgentScope initialization for CoDevx v4.0
================================================================
Initializes AgentScope with multi-backend model support.
Gracefully no-ops if AgentScope is not installed or no API key is present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# add_log is imported lazily inside init_agentscope() to avoid circular imports
# when this module is loaded before agent_mesh.py has finished initializing.


@dataclass
class AgentScopeConfig:
    """Runtime configuration snapshot returned by init_agentscope()."""

    enabled: bool = False
    model_config_name: str = ""
    model_type: str = ""
    model_name: str = ""
    max_tokens: int = 4000
    temperature: float = 0.4
    msghub_rounds: int = 2
    memory_backend: str = "ListMemory + SQLite"
    hub_topology: str = "ArchitectAgent ↔ FrontendDevAgent ↔ BackendDevAgent"
    extra: dict[str, Any] = field(default_factory=dict)


def _build_model_configs() -> list[dict[str, Any]]:
    """
    Build AgentScope model config list from environment variables.

    Priority:
    1. OpenAI (default, always attempted when OPENAI_API_KEY is set)
    2. Anthropic  (when ANTHROPIC_API_KEY is present)
    3. Ollama     (when OLLAMA_BASE_URL is present)
    """
    model_name = os.getenv("LLM_MODEL", "gpt-4o")
    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.4"))

    configs: list[dict[str, Any]] = []

    # ── OpenAI / LiteLLM-compatible ──────────────────────────────────────────
    openai_key = os.getenv("OPENAI_API_KEY", "")
    openai_base = os.getenv("OPENAI_BASE_URL", "")
    if openai_key:
        cfg: dict[str, Any] = {
            "config_name": "codevx-primary",
            "model_type": "openai_chat",
            "model_name": model_name,
            "api_key": openai_key,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if openai_base:
            cfg["client_args"] = {"base_url": openai_base}
        configs.append(cfg)

    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        anthropic_model = (
            model_name
            if model_name.startswith("claude")
            else "claude-3-5-sonnet-20241022"
        )
        configs.append(
            {
                "config_name": "codevx-anthropic",
                "model_type": "anthropic_chat",
                "model_name": anthropic_model,
                "api_key": anthropic_key,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )

    # ── Ollama (local) ───────────────────────────────────────────────────────
    ollama_base = os.getenv("OLLAMA_BASE_URL", "")
    if ollama_base:
        ollama_model = (
            model_name if model_name.startswith("llama") else "llama3.1:70b"
        )
        configs.append(
            {
                "config_name": "codevx-ollama",
                "model_type": "ollama_chat",
                "model_name": ollama_model,
                "host": ollama_base,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
        )

    return configs


def init_agentscope() -> AgentScopeConfig | None:
    """
    Initialize AgentScope and return an AgentScopeConfig.

    Returns:
        AgentScopeConfig with enabled=True on success.
        AgentScopeConfig with enabled=False (no-op) when:
          - agentscope package is not installed
          - AGENTSCOPE_ENABLED=false in env
          - No API key is configured (OPENAI_API_KEY / ANTHROPIC_API_KEY)
        None on unexpected error.
    """
    # Allow callers to import add_log after agent_mesh has initialised
    try:
        from agent_mesh import add_log as _add_log  # type: ignore[import]
    except ImportError:
        import logging

        def _add_log(msg: str) -> None:  # type: ignore[misc]
            logging.getLogger(__name__).info(msg)

    enabled_env = os.getenv("AGENTSCOPE_ENABLED", "true").lower()
    if enabled_env in {"false", "0", "no"}:
        _add_log("[AgentScope] AGENTSCOPE_ENABLED=false — skipping init.")
        return AgentScopeConfig(enabled=False)

    # ── Check API keys ───────────────────────────────────────────────────────
    has_key = bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OLLAMA_BASE_URL")
    )
    if not has_key:
        _add_log(
            "[AgentScope] No API key / OLLAMA_BASE_URL found — "
            "AgentScope disabled (simulation mode preserved)."
        )
        return AgentScopeConfig(enabled=False)

    # ── Try importing AgentScope ─────────────────────────────────────────────
    try:
        import agentscope  # type: ignore[import]
    except ImportError:
        _add_log(
            "[AgentScope] Package not installed — "
            "run: pip install agentscope>=0.0.6  (falling back to legacy pipeline)."
        )
        return AgentScopeConfig(enabled=False)

    # ── Build model configs ──────────────────────────────────────────────────
    model_configs = _build_model_configs()
    if not model_configs:
        _add_log("[AgentScope] No valid model config built — disabling.")
        return AgentScopeConfig(enabled=False)

    try:
        agentscope.init(
            model_configs=model_configs,
            project="CoDevx",
            save_log=False,   # we use our own add_log()
            save_code=False,
        )
    except Exception as exc:
        _add_log(f"[AgentScope][ERROR] agentscope.init() failed: {exc}")
        return AgentScopeConfig(enabled=False)

    primary = model_configs[0]
    msghub_rounds = int(os.getenv("MSGHUB_ROUNDS", "2"))

    cfg = AgentScopeConfig(
        enabled=True,
        model_config_name=primary.get("config_name", "codevx-primary"),
        model_type=primary.get("model_type", "openai_chat"),
        model_name=primary.get("model_name", os.getenv("LLM_MODEL", "gpt-4o")),
        max_tokens=primary.get("max_tokens", 4000),
        temperature=primary.get("temperature", 0.4),
        msghub_rounds=msghub_rounds,
        memory_backend="ListMemory + SQLite",
        hub_topology="ArchitectAgent ↔ FrontendDevAgent ↔ BackendDevAgent",
        extra={"available_configs": [c["config_name"] for c in model_configs]},
    )

    _add_log(
        f"[AgentScope] ✅ Initialized — model={cfg.model_name} "
        f"type={cfg.model_type} msghub_rounds={cfg.msghub_rounds}"
    )
    return cfg
