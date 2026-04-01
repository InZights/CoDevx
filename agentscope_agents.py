"""
agentscope_agents.py — AgentScope agent wrappers for CoDevx v4.0
=================================================================
Implements all 8 agents as AgentScope DialogAgent / ReActAgent instances,
each backed by a ListMemory for in-context recall and a SQLite-persisted
cross-session memory layer (via agent_mesh.db).

All AgentScope imports are inside try/except so the module loads cleanly
even when AgentScope is not installed.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

# ---------------------------------------------------------------------------
# Safe AgentScope imports
# ---------------------------------------------------------------------------
try:
    from agentscope.agents import DialogAgent  # type: ignore[import]
    from agentscope.message import Msg  # type: ignore[import]
    from agentscope.memory import ListMemory  # type: ignore[import]

    _AS_AVAILABLE = True
except ImportError:
    _AS_AVAILABLE = False

    # Minimal stubs so the rest of the module type-checks cleanly
    class Msg:  # type: ignore[no-redef]
        def __init__(self, name: str, content: str, role: str = "user") -> None:
            self.name = name
            self.content = content
            self.role = role

    class ListMemory:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self._items: list[str] = []

        def add(self, msg: Any) -> None:
            self._items.append(str(getattr(msg, "content", msg)))

        def get_memory(self) -> list[Any]:
            return self._items

    class DialogAgent:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Agent system prompts (imported from agent_mesh to stay in sync)
# ---------------------------------------------------------------------------
try:
    from agent_mesh import AGENT_SYSTEM_PROMPTS  # type: ignore[import]
except ImportError:
    AGENT_SYSTEM_PROMPTS: dict[str, str] = {}  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Base wrapper
# ---------------------------------------------------------------------------

class CoDevxAgentBase:
    """
    Thin wrapper around an AgentScope DialogAgent (or stub) that:
      - Holds a ListMemory for in-context recall
      - Exposes recall_and_inject_memories() for SQLite → ListMemory bridging
      - Wraps the synchronous AgentScope __call__ so async callers can await it
      - Falls back gracefully to simulation when AgentScope is unavailable
    """

    #: Override in subclasses
    AGENT_NAME: str = "Agent"
    DEFAULT_TEMPERATURE: float = 0.4

    def __init__(self, model_config_name: str = "codevx-primary") -> None:
        self.model_config_name = model_config_name
        self.memory = ListMemory()
        self._inner: Any = None

        if _AS_AVAILABLE:
            try:
                system_prompt = AGENT_SYSTEM_PROMPTS.get(self.AGENT_NAME, "")
                self._inner = DialogAgent(
                    name=self.AGENT_NAME,
                    sys_prompt=system_prompt,
                    model_config_name=model_config_name,
                    memory=self.memory,
                )
            except Exception as exc:
                _warn(f"[AgentScope] Could not create DialogAgent for {self.AGENT_NAME}: {exc}")

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def recall_and_inject_memories(
        self, task_id: str, db_memories: list[str]
    ) -> None:
        """Load SQLite memories into the agent's ListMemory."""
        for mem in db_memories:
            msg = Msg(name="memory", content=mem, role="user")
            self.memory.add(msg)

    def _memory_context(self) -> str:
        try:
            from agent_mesh import MEMORY_CONTEXT_K as _k  # type: ignore[import]
        except ImportError:
            _k = 5
        items = self.memory.get_memory()
        if not items:
            return "No prior memories."
        lines = []
        for item in items[-_k:]:
            content = getattr(item, "content", str(item))
            lines.append(f"- {content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Core invocation
    # ------------------------------------------------------------------

    async def run(self, user_message: str) -> dict[str, Any]:
        """
        Invoke the agent asynchronously and return a parsed response dict
        with keys: summary, files, notes.
        """
        if self._inner is None or not _AS_AVAILABLE:
            return self._simulate(user_message)

        msg = Msg(name="user", content=user_message, role="user")
        try:
            # AgentScope agents are synchronous — offload to thread pool
            raw_response = await asyncio.to_thread(self._inner, msg)
            content = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
            return _parse_response(content)
        except Exception as exc:
            _warn(f"[AgentScope][{self.AGENT_NAME}] LLM call failed: {exc} — using simulation.")
            return self._simulate(user_message)

    def _simulate(self, user_message: str) -> dict[str, Any]:
        return {
            "summary": f"[SIMULATION] {self.AGENT_NAME} — set OPENAI_API_KEY for real output.",
            "files": [],
            "notes": [f"{self.AGENT_NAME} ran in AgentScope simulation mode."],
        }


# ---------------------------------------------------------------------------
# Tool-using agent base (ReActAgent when available)
# ---------------------------------------------------------------------------

class CoDevxToolAgent(CoDevxAgentBase):
    """
    Agent variant that uses ReActAgent when AgentScope is available,
    falling back to DialogAgent if ReActAgent is not importable.
    """

    def __init__(
        self,
        model_config_name: str = "codevx-primary",
        service_toolkit: Any = None,
    ) -> None:
        self.model_config_name = model_config_name
        self.memory = ListMemory()
        self._inner = None

        if _AS_AVAILABLE:
            system_prompt = AGENT_SYSTEM_PROMPTS.get(self.AGENT_NAME, "")
            try:
                from agentscope.agents import ReActAgent  # type: ignore[import]

                self._inner = ReActAgent(
                    name=self.AGENT_NAME,
                    sys_prompt=system_prompt,
                    model_config_name=model_config_name,
                    tools=service_toolkit,
                    memory=self.memory,
                )
            except (ImportError, Exception):
                # Fallback to DialogAgent
                try:
                    self._inner = DialogAgent(
                        name=self.AGENT_NAME,
                        sys_prompt=system_prompt,
                        model_config_name=model_config_name,
                        memory=self.memory,
                    )
                except Exception as exc:
                    _warn(f"[AgentScope] Could not create agent for {self.AGENT_NAME}: {exc}")


# ---------------------------------------------------------------------------
# Concrete agent classes (one per role)
# ---------------------------------------------------------------------------

class ProjectManagerAgent(CoDevxAgentBase):
    AGENT_NAME = "Project Manager"
    DEFAULT_TEMPERATURE = 0.3


class ArchitectAgent(CoDevxAgentBase):
    AGENT_NAME = "Architect"
    DEFAULT_TEMPERATURE = 0.4


class FrontendDevAgent(CoDevxAgentBase):
    AGENT_NAME = "Frontend Dev"
    DEFAULT_TEMPERATURE = 0.6


class BackendDevAgent(CoDevxAgentBase):
    AGENT_NAME = "Backend Dev"
    DEFAULT_TEMPERATURE = 0.4


class DatabaseEngineerAgent(CoDevxAgentBase):
    AGENT_NAME = "Database Engineer"
    DEFAULT_TEMPERATURE = 0.25


class QAEngineerAgent(CoDevxToolAgent):
    """QA Engineer — gets run_pytest tool registered so it can autonomously re-run tests."""

    AGENT_NAME = "QA Engineer"
    DEFAULT_TEMPERATURE = 0.3


class SecurityAnalystAgent(CoDevxToolAgent):
    """Security Analyst — gets run_bandit + run_npm_audit tools."""

    AGENT_NAME = "Security Analyst"
    DEFAULT_TEMPERATURE = 0.2


class DevOpsEngineerAgent(CoDevxToolAgent):
    """DevOps Engineer — gets git_commit_push tool."""

    AGENT_NAME = "DevOps Engineer"
    DEFAULT_TEMPERATURE = 0.35


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_agents(
    model_config_name: str = "codevx-primary",
    qa_toolkit: Any = None,
    security_toolkit: Any = None,
    devops_toolkit: Any = None,
) -> dict[str, CoDevxAgentBase]:
    """
    Instantiate all 8 agents, returning a dict keyed by agent name.

    Args:
        model_config_name:  AgentScope model config name (from init).
        qa_toolkit:         ServiceToolkit for QAEngineerAgent.
        security_toolkit:   ServiceToolkit for SecurityAnalystAgent.
        devops_toolkit:     ServiceToolkit for DevOpsEngineerAgent.
    """
    return {
        "Project Manager":   ProjectManagerAgent(model_config_name),
        "Architect":         ArchitectAgent(model_config_name),
        "Frontend Dev":      FrontendDevAgent(model_config_name),
        "Backend Dev":       BackendDevAgent(model_config_name),
        "Database Engineer": DatabaseEngineerAgent(model_config_name),
        "QA Engineer":       QAEngineerAgent(model_config_name, qa_toolkit),
        "Security Analyst":  SecurityAnalystAgent(model_config_name, security_toolkit),
        "DevOps Engineer":   DevOpsEngineerAgent(model_config_name, devops_toolkit),
    }


# ---------------------------------------------------------------------------
# MsgHub collaboration helpers
# ---------------------------------------------------------------------------

async def msghub_collaboration_round(
    agents: list[CoDevxAgentBase],
    broadcast_message: str,
    rounds: int = 2,
) -> list[dict[str, Any]]:
    """
    Simulate an AgentScope MsgHub collaboration round.

    Each agent receives the broadcast message and may ask/answer questions
    to other agents in the hub.  Returns a list of agent responses.

    When AgentScope MsgHub is available the native context manager is used;
    otherwise the agents are called sequentially with accumulated context.
    """
    responses: list[dict[str, Any]] = []

    if _AS_AVAILABLE:
        try:
            from agentscope.msghub import msghub  # type: ignore[import]

            participant_inners = [a._inner for a in agents if a._inner is not None]
            if participant_inners:
                # Run collaboration inside the MsgHub context (synchronous AgentScope API)
                async def _hub_run() -> list[dict[str, Any]]:
                    hub_results: list[dict[str, Any]] = []

                    def _sync_hub() -> list[dict[str, Any]]:
                        with msghub(participant_inners):
                            broadcast_msg = Msg(
                                name="Architect",
                                content=broadcast_message,
                                role="user",
                            )
                            # First round: all agents receive the architecture broadcast
                            for agent_obj in agents:
                                if agent_obj._inner is not None:
                                    resp = agent_obj._inner(broadcast_msg)
                                    hub_results.append(_parse_response(
                                        resp.content if hasattr(resp, "content") else str(resp)
                                    ))

                            # Subsequent collaboration rounds
                            for _round in range(rounds - 1):
                                for idx, agent_obj in enumerate(agents):
                                    if agent_obj._inner is None:
                                        continue
                                    # Each agent can query the others based on previous responses
                                    context = "\n\n".join(
                                        f"{a.AGENT_NAME}: {r.get('summary', '')}"
                                        for a, r in zip(agents, hub_results)
                                        if r
                                    )
                                    follow_up = Msg(
                                        name=agent_obj.AGENT_NAME,
                                        content=(
                                            f"Collaboration round {_round + 2}: "
                                            f"Given the following context from your colleagues, "
                                            f"refine your implementation:\n\n{context}"
                                        ),
                                        role="user",
                                    )
                                    resp = agent_obj._inner(follow_up)
                                    if idx < len(hub_results):
                                        hub_results[idx] = _parse_response(
                                            resp.content if hasattr(resp, "content") else str(resp)
                                        )
                        return hub_results

                    return await asyncio.to_thread(_sync_hub)

                responses = await _hub_run()
                if responses:
                    return responses
        except (ImportError, Exception) as exc:
            _warn(f"[AgentScope][MsgHub] Hub unavailable ({exc}), running sequentially.")

    # Fallback: sequential collaboration with accumulated context
    accumulated_context = broadcast_message
    for agent_obj in agents:
        resp = await agent_obj.run(accumulated_context)
        responses.append(resp)
        # Feed this agent's summary back into the context for subsequent agents
        summary = resp.get("summary", "")
        if summary:
            accumulated_context += (
                f"\n\n[{agent_obj.AGENT_NAME} response]: {summary}"
            )

    return responses


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> dict[str, Any]:
    """Parse JSON from AgentScope Msg.content, stripping markdown fences."""
    text = raw.strip()
    # strip markdown code fences if any
    import re
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {"summary": text, "files": [], "notes": []}


def _warn(msg: str) -> None:
    try:
        from agent_mesh import add_log  # type: ignore[import]
        add_log(msg)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(msg)
