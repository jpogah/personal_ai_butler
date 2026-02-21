"""Screenshot tool: browser or desktop screenshot → returns file path."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def take_screenshot(
    target: str = "browser",
    output_dir: str = "./data/media",
    browser_kwargs: Optional[dict] = None,
) -> str:
    """
    Capture a screenshot.

    Args:
        target: 'browser' (current browser page) or 'desktop' (full screen)
        output_dir: directory to save screenshot
        browser_kwargs: extra kwargs for browser_tool._get_page()

    Returns:
        File path on success, error string on failure.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = str(Path(output_dir) / f"screenshot_{int(time.time())}.png")

    if target == "browser":
        from .browser_tool import browser_screenshot
        result = await browser_screenshot(output_path, **(browser_kwargs or {}))
        if result.startswith("[ERROR]"):
            return result
        return result  # returns path

    elif target == "desktop":
        return await _desktop_screenshot(output_path)

    else:
        return f"[ERROR] Unknown target: {target!r}. Use 'browser' or 'desktop'."


async def _desktop_screenshot(output_path: str) -> str:
    """Use macOS screencapture CLI to capture the desktop."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "screencapture",
            "-x",          # no sound
            "-t", "png",
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return f"[ERROR] screencapture failed: {stdout.decode().strip()}"
        if not Path(output_path).exists():
            return "[ERROR] screencapture ran but output file not found"
        logger.info("Desktop screenshot saved to %s", output_path)
        return output_path
    except asyncio.TimeoutError:
        return "[ERROR] screencapture timed out"
    except FileNotFoundError:
        return "[ERROR] screencapture not found — are you on macOS?"
    except Exception as e:
        return f"[ERROR] {e}"
