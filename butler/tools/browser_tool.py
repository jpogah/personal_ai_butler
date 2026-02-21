"""Browser automation tool using Playwright."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_browser_instance = None
_page_instance = None
_playwright_instance = None


async def _get_page(user_data_dir: str = "./data/browser_profile", headless: bool = True):
    """Get or create a persistent browser page."""
    global _browser_instance, _page_instance, _playwright_instance

    if _page_instance is not None:
        try:
            # Quick check page is still alive
            await _page_instance.title()
            return _page_instance
        except Exception:
            _page_instance = None
            _browser_instance = None

    from playwright.async_api import async_playwright

    if _playwright_instance is None:
        _playwright_instance = await async_playwright().start()

    profile_dir = Path(user_data_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    _browser_instance = await _playwright_instance.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1280, "height": 900},
    )
    _page_instance = _browser_instance.pages[0] if _browser_instance.pages else await _browser_instance.new_page()
    logger.info("Browser initialized (headless=%s)", headless)
    return _page_instance


async def browser_navigate(url: str, wait_until: str = "domcontentloaded", **kwargs) -> str:
    """Navigate to a URL and return the page title."""
    try:
        page = await _get_page(**kwargs)
        response = await page.goto(url, wait_until=wait_until, timeout=30000)
        title = await page.title()
        status = response.status if response else "?"
        return f"[OK] Navigated to {url} (status {status}, title: {title!r})"
    except Exception as e:
        return f"[ERROR] Navigation failed: {e}"


async def browser_click(selector: str, **kwargs) -> str:
    """Click an element by CSS selector or text."""
    try:
        page = await _get_page(**kwargs)
        await page.click(selector, timeout=10000)
        return f"[OK] Clicked: {selector}"
    except Exception as e:
        return f"[ERROR] Click failed: {e}"


async def browser_type(selector: str, text: str, **kwargs) -> str:
    """Type text into an element."""
    try:
        page = await _get_page(**kwargs)
        await page.fill(selector, text, timeout=10000)
        return f"[OK] Typed into {selector}"
    except Exception as e:
        return f"[ERROR] Type failed: {e}"


async def browser_get_text(selector: str = "body", max_chars: int = 8000, **kwargs) -> str:
    """Extract text content from the page or a specific element."""
    try:
        page = await _get_page(**kwargs)
        if selector == "body":
            text = await page.evaluate("document.body.innerText")
        else:
            element = await page.query_selector(selector)
            if not element:
                return f"[ERROR] Element not found: {selector}"
            text = await element.inner_text()

        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars - 100] + f"\n…[truncated, {len(text)} chars total]"
        return text or "[empty]"
    except Exception as e:
        return f"[ERROR] get_text failed: {e}"


async def browser_screenshot(output_path: Optional[str] = None, **kwargs) -> str:
    """Take a screenshot of the current browser page."""
    try:
        page = await _get_page(**kwargs)
        if not output_path:
            import time
            output_path = f"./data/media/screenshot_{int(time.time())}.png"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=output_path, full_page=False)
        return output_path
    except Exception as e:
        return f"[ERROR] Screenshot failed: {e}"


async def close_browser() -> None:
    global _browser_instance, _page_instance, _playwright_instance
    if _browser_instance:
        try:
            await _browser_instance.close()
        except Exception:
            pass
    if _playwright_instance:
        try:
            await _playwright_instance.stop()
        except Exception:
            pass
    _browser_instance = None
    _page_instance = None
    _playwright_instance = None
