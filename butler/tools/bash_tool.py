"""Sandboxed bash tool."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from ..permissions.classifier import RiskLevel, classify_bash
from ..permissions.approval import ApprovalManager

logger = logging.getLogger(__name__)

# Commands that are always blocked regardless of user approval
_BLOCKLIST: list[re.Pattern] = [
    re.compile(r"rm\s+-[rf]+\s*/\b"),
    re.compile(r":\(\)\s*\{.*\|.*\&"),           # fork bomb
    re.compile(r"dd\s+if=/dev/(random|zero|urandom)\s+of=/dev/sd"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bmkfs\b"),
]

# Sanitized environment for subprocesses
_SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "SHELL", "TMPDIR", "XDG_RUNTIME_DIR",
    "PLAYWRIGHT_BROWSERS_PATH",
}


def _sanitize_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}


def _is_blocked(command: str) -> bool:
    for pattern in _BLOCKLIST:
        if pattern.search(command):
            return True
    return False


async def run_bash(
    command: str,
    approver: Optional[ApprovalManager],
    timeout: float = 30.0,
    auto_approve_below: RiskLevel = RiskLevel.LOW,
) -> str:
    """
    Execute a shell command safely.
    Returns stdout+stderr output as a string, or an error message.
    """
    if _is_blocked(command):
        return f"[BLOCKED] This command is permanently blocked for safety: {command!r}"

    risk = classify_bash(command)

    if approver and risk > auto_approve_below:
        approved = await approver.request_approval("bash", {"command": command}, risk)
        if not approved:
            return f"[DENIED] User denied execution of: {command!r}"

    logger.info("Running bash [%s]: %s", risk.name, command[:200])

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_sanitize_env(),
            limit=1024 * 1024,  # 1 MB pipe buffer
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"[TIMEOUT] Command timed out after {timeout}s"

        output = stdout.decode(errors="replace")
        # Cap at 8000 chars to avoid flooding chat
        if len(output) > 8000:
            output = output[:7900] + f"\n…[truncated, {len(output)} chars total]"

        exit_code = proc.returncode
        if exit_code != 0:
            return f"[exit {exit_code}]\n{output}"
        return output or "[no output]"

    except Exception as e:
        logger.error("Bash execution error: %s", e, exc_info=True)
        return f"[ERROR] {e}"
