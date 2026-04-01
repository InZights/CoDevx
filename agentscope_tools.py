"""
agentscope_tools.py — AgentScope ServiceToolkit for CoDevx v4.0
================================================================
Registers run_pytest, run_bandit, run_npm_audit, git_commit_push,
write_workspace_file, and read_project_architecture as AgentScope
service functions.

All AgentScope imports are inside try/except for graceful degradation.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

# ---------------------------------------------------------------------------
# Safe AgentScope import
# ---------------------------------------------------------------------------
try:
    from agentscope.service import ServiceToolkit  # type: ignore[import]
    from agentscope.service.service_response import (  # type: ignore[import]
        ServiceExecStatus,
        ServiceResponse,
    )

    _AS_AVAILABLE = True
except ImportError:
    _AS_AVAILABLE = False

    class ServiceExecStatus:  # type: ignore[no-redef]
        SUCCESS = "SUCCESS"
        ERROR = "ERROR"

    class ServiceResponse:  # type: ignore[no-redef]
        def __init__(self, status: str, content: Any) -> None:
            self.status = status
            self.content = content

    class ServiceToolkit:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self._tools: list[Any] = []

        def add(self, func: Any, **kwargs: Any) -> None:
            self._tools.append(func)


# ---------------------------------------------------------------------------
# Async → sync bridge helper
# ---------------------------------------------------------------------------

def _run_sync(coro: Any) -> Any:
    """Run an async coroutine synchronously from a sync service function."""
    try:
        loop = asyncio.get_running_loop()
        # A running event loop exists — use run_coroutine_threadsafe from a thread
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=300)
    except RuntimeError:
        # No running event loop — safe to use asyncio.run()
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def run_pytest_service(workspace_path: str = "") -> ServiceResponse:
    """
    Run pytest on the generated workspace.

    Execute the full pytest suite with coverage reporting.
    Returns a ServiceResponse with status SUCCESS/ERROR and
    a dict containing: passed (bool), output (str), test_count (int).

    Args:
        workspace_path: Absolute path to the workspace directory.
                        Defaults to GIT_WORKSPACE env var.
    """
    try:
        from agent_mesh import run_pytest, GIT_WORKSPACE  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    cwd = workspace_path or GIT_WORKSPACE
    passed, output, count = _run_sync(run_pytest(cwd))
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS if passed else ServiceExecStatus.ERROR,
        content={
            "passed": passed,
            "output": output,
            "test_count": count,
            "workspace": cwd,
        },
    )


def run_bandit_service(workspace_path: str = "") -> ServiceResponse:
    """
    Run Bandit SAST security scan on Python source files.

    Scans for OWASP Top 10 and CWE Top 25 vulnerabilities.
    Returns a ServiceResponse with status SUCCESS when clean (no HIGH/CRITICAL)
    or ERROR when high-severity findings are detected.

    Args:
        workspace_path: Absolute path to the workspace directory.
                        Defaults to GIT_WORKSPACE env var.
    """
    try:
        from agent_mesh import run_bandit, GIT_WORKSPACE  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    cwd = workspace_path or GIT_WORKSPACE
    clean, output = _run_sync(run_bandit(cwd))
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS if clean else ServiceExecStatus.ERROR,
        content={
            "clean": clean,
            "output": output,
            "workspace": cwd,
        },
    )


def run_npm_audit_service(workspace_path: str = "") -> ServiceResponse:
    """
    Run npm audit to check for known dependency vulnerabilities.

    Checks JavaScript/TypeScript dependencies for HIGH and CRITICAL CVEs.
    Returns SUCCESS when no HIGH+ findings, ERROR otherwise.

    Args:
        workspace_path: Absolute path to the workspace directory.
                        Defaults to GIT_WORKSPACE env var.
    """
    try:
        from agent_mesh import run_npm_audit, GIT_WORKSPACE  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    cwd = workspace_path or GIT_WORKSPACE
    clean, output = _run_sync(run_npm_audit(cwd))
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS if clean else ServiceExecStatus.ERROR,
        content={
            "clean": clean,
            "output": output,
            "workspace": cwd,
        },
    )


def git_commit_push_service(
    task_id: str,
    branch: str,
    file_paths: str = "",
) -> ServiceResponse:
    """
    Create a branch, commit all generated files, push, and open a GitHub PR.

    Args:
        task_id:    Short task UUID (used for commit message and PR title).
        branch:     Feature branch name (e.g. 'feat/abc123').
        file_paths: Comma-separated list of relative file paths generated.
    """
    try:
        from agent_mesh import git_commit_push  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    paths = [p.strip() for p in file_paths.split(",") if p.strip()]
    pr_url = _run_sync(git_commit_push(task_id, branch, paths))
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS,
        content={
            "pr_url": pr_url,
            "branch": branch,
            "task_id": task_id,
        },
    )


def write_file_service(
    task_id: str,
    relative_path: str,
    content: str,
) -> ServiceResponse:
    """
    Write a generated file to the workspace directory and persist to SQLite.

    Args:
        task_id:       Task UUID for DB association.
        relative_path: Path relative to workspace root (e.g. 'src/routes/users.py').
        content:       Full file content to write.
    """
    try:
        from agent_mesh import write_workspace_file  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    _run_sync(write_workspace_file(task_id, relative_path, content))
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS,
        content={"path": relative_path, "task_id": task_id},
    )


def read_architecture_service() -> ServiceResponse:
    """
    Read the living project architecture document from the workspace.

    Returns the current PROJECT_ARCHITECTURE.md content so agents can
    understand the existing system before proposing changes.
    """
    try:
        from agent_mesh import _read_project_architecture  # type: ignore[import]
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content={"error": "agent_mesh not available"},
        )

    content = _read_project_architecture()
    return ServiceResponse(
        status=ServiceExecStatus.SUCCESS,
        content={"architecture": content or "(No existing architecture document.)"},
    )


# ---------------------------------------------------------------------------
# Toolkit factory
# ---------------------------------------------------------------------------

def build_qa_toolkit() -> ServiceToolkit:
    """Build a ServiceToolkit for the QA Engineer agent."""
    toolkit = ServiceToolkit()
    toolkit.add(run_pytest_service)
    return toolkit


def build_security_toolkit() -> ServiceToolkit:
    """Build a ServiceToolkit for the Security Analyst agent."""
    toolkit = ServiceToolkit()
    toolkit.add(run_bandit_service)
    toolkit.add(run_npm_audit_service)
    return toolkit


def build_devops_toolkit() -> ServiceToolkit:
    """Build a ServiceToolkit for the DevOps Engineer agent."""
    toolkit = ServiceToolkit()
    toolkit.add(git_commit_push_service)
    toolkit.add(write_file_service)
    return toolkit


def build_full_toolkit() -> ServiceToolkit:
    """Build a ServiceToolkit with all registered service functions."""
    toolkit = ServiceToolkit()
    toolkit.add(run_pytest_service)
    toolkit.add(run_bandit_service)
    toolkit.add(run_npm_audit_service)
    toolkit.add(git_commit_push_service)
    toolkit.add(write_file_service)
    toolkit.add(read_architecture_service)
    return toolkit
