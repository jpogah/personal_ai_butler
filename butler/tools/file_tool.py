"""File system tool: read, write, list, and send files to user."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Callable, Awaitable

from ..permissions.classifier import RiskLevel
from ..permissions.approval import ApprovalManager

logger = logging.getLogger(__name__)

# Type for send-to-user callback
SendFileFn = Callable[[str, str], Awaitable[None]]  # (recipient_id, file_path)


async def file_read(
    path: str,
    max_bytes: int = 100_000,
) -> str:
    """Read a file and return its contents (capped at max_bytes)."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"[ERROR] File not found: {path}"
        if not p.is_file():
            return f"[ERROR] Not a file: {path}"

        size = p.stat().st_size
        with open(p, "r", errors="replace") as f:
            content = f.read(max_bytes)

        if size > max_bytes:
            content += f"\n…[truncated — file is {size} bytes, showing first {max_bytes}]"
        return content
    except PermissionError:
        return f"[ERROR] Permission denied: {path}"
    except Exception as e:
        return f"[ERROR] {e}"


async def file_write(
    path: str,
    content: str,
    approver: Optional[ApprovalManager],
) -> str:
    """Write content to a file (requires MEDIUM approval)."""
    if approver:
        approved = await approver.request_approval(
            "file_write",
            {"path": path, "content_preview": content[:200]},
            RiskLevel.MEDIUM,
        )
        if not approved:
            return f"[DENIED] Write to {path!r} was denied."

    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info("Wrote %d bytes to %s", len(content), path)
        return f"[OK] Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"[ERROR] {e}"


async def file_list(
    directory: str,
    show_hidden: bool = False,
    max_entries: int = 200,
) -> str:
    """List files in a directory."""
    try:
        p = Path(directory).expanduser()
        if not p.exists():
            return f"[ERROR] Directory not found: {directory}"
        if not p.is_dir():
            return f"[ERROR] Not a directory: {directory}"

        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        lines = []
        for entry in entries[:max_entries]:
            if entry.is_dir():
                lines.append(f"📁 {entry.name}/")
            else:
                size = entry.stat().st_size
                size_str = _human_size(size)
                lines.append(f"📄 {entry.name} ({size_str})")

        result = "\n".join(lines) if lines else "(empty directory)"
        if len(entries) > max_entries:
            result += f"\n…[{len(entries) - max_entries} more entries not shown]"
        return f"Contents of {directory}:\n{result}"
    except PermissionError:
        return f"[ERROR] Permission denied: {directory}"
    except Exception as e:
        return f"[ERROR] {e}"


async def file_send(
    path: str,
    recipient_id: str,
    channel: str,
    send_file_fn: SendFileFn,
) -> str:
    """Copy a file to staging area and send it to the user via chat."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"[ERROR] File not found: {path}"
        if not p.is_file():
            return f"[ERROR] Not a file: {path}"

        await send_file_fn(recipient_id, str(p))
        return f"[OK] Sent {p.name} to user"
    except Exception as e:
        return f"[ERROR] {e}"


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
