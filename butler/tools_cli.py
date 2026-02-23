"""
Butler CLI Tool Runner
======================
Exposes all butler tools as bash-callable commands so the Claude Code CLI
can use them in non-API (Max subscription) mode.

Usage:
    python3 -m butler.tools_cli <tool_name> '<json_args>'

Examples:
    python3 -m butler.tools_cli browser_navigate '{"url":"https://google.com"}'
    python3 -m butler.tools_cli browser_screenshot '{}'
    python3 -m butler.tools_cli browser_get_text '{"selector":"body"}'
    python3 -m butler.tools_cli screenshot '{"target":"desktop"}'
    python3 -m butler.tools_cli email_list '{"count":10}'
    python3 -m butler.tools_cli email_read '{"message_id":"42"}'
    python3 -m butler.tools_cli file_read '{"path":"~/Desktop/notes.txt"}'
    python3 -m butler.tools_cli file_list '{"directory":"~/Desktop"}'
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


def _load_config():
    """Load butler config, searching up from cwd and script location."""
    candidates = [
        Path.cwd() / "config" / "butler.yaml",
        Path(__file__).parent.parent / "config" / "butler.yaml",
    ]
    for p in candidates:
        if p.exists():
            from butler.config import load_config
            return load_config(str(p))
    return None


async def _run(tool_name: str, args: dict) -> str:
    cfg = _load_config()

    # ── Browser tools ──────────────────────────────────────────────────────
    browser_kwargs = {}
    if cfg and cfg.browser_enabled:
        browser_kwargs = {
            "user_data_dir": cfg.browser_user_data_dir,
            "headless": cfg.browser_headless,
        }

    if tool_name == "browser_navigate":
        from butler.tools.browser_tool import browser_navigate
        return await browser_navigate(args["url"], **browser_kwargs)

    elif tool_name == "browser_open":
        # Navigate + screenshot in one process call (avoids blank screenshot issue)
        from butler.tools.browser_tool import browser_navigate, browser_screenshot
        import time
        nav_result = await browser_navigate(args["url"], **browser_kwargs)
        await asyncio.sleep(2)  # let page fully render
        media_dir = cfg.media_dir if cfg else "./data/media"
        out_path = str(Path(media_dir) / f"screenshot_{int(time.time())}.png")
        shot_path = await browser_screenshot(output_path=out_path, **browser_kwargs)
        return f"{nav_result}\nScreenshot: {shot_path}"

    elif tool_name == "browser_click":
        from butler.tools.browser_tool import browser_click
        return await browser_click(args["selector"], **browser_kwargs)

    elif tool_name == "browser_type":
        from butler.tools.browser_tool import browser_type
        return await browser_type(args["selector"], args["text"], **browser_kwargs)

    elif tool_name == "browser_get_text":
        from butler.tools.browser_tool import browser_get_text
        return await browser_get_text(args.get("selector", "body"), **browser_kwargs)

    elif tool_name == "browser_screenshot":
        from butler.tools.browser_tool import browser_screenshot
        out = args.get("output_path")
        result = await browser_screenshot(output_path=out, **browser_kwargs)
        return result  # returns file path on success

    # ── Screenshot ────────────────────────────────────────────────────────
    elif tool_name == "screenshot":
        from butler.tools.screenshot_tool import take_screenshot
        target = args.get("target", "desktop")
        media_dir = cfg.media_dir if cfg else "./data/media"
        return await take_screenshot(target=target, output_dir=media_dir, browser_kwargs=browser_kwargs)

    # ── File tools ────────────────────────────────────────────────────────
    elif tool_name == "file_read":
        from butler.tools.file_tool import file_read
        return await file_read(args["path"], max_bytes=args.get("max_bytes", 100_000))

    elif tool_name == "file_list":
        from butler.tools.file_tool import file_list
        return await file_list(
            args["directory"],
            show_hidden=args.get("show_hidden", False),
        )

    elif tool_name == "file_write":
        from butler.tools.file_tool import file_write
        # No approval in CLI mode — Claude itself is the authorized actor
        return await file_write(args["path"], args["content"], approver=None)

    # ── Email tools ───────────────────────────────────────────────────────
    elif tool_name in ("email_list", "email_read", "email_send"):
        if not cfg or not cfg.email_enabled:
            return "[ERROR] Email not configured. Enable it in config/butler.yaml."
        from butler.tools.email_tool import EmailTool

        # Build email tool instances for all configured accounts
        email_tools = {
            name: EmailTool(acct.get("imap", {}), acct.get("smtp", {}))
            for name, acct in cfg.email_accounts.items()
        }
        if not email_tools:
            return "[ERROR] No email accounts configured."

        # Select account by name, falling back to first available
        account = args.get("account")
        if account and account in email_tools:
            email = email_tools[account]
        else:
            email = next(iter(email_tools.values()))
            if account:
                available = ", ".join(email_tools.keys())
                return f"[ERROR] Unknown account '{account}'. Available: {available}"

        if tool_name == "email_list":
            return await email.list_emails(
                count=args.get("count", 10),
                folder=args.get("folder", "INBOX"),
            )
        elif tool_name == "email_read":
            return await email.read_email(args["message_id"])
        elif tool_name == "email_send":
            # No approval in CLI mode
            return await email.send_email(
                args["to"], args["subject"], args["body"], approver=None
            )

    # ── LinkedIn login helper (one-time setup) ────────────────────────────
    elif tool_name == "linkedin_login":
        from butler.tools.browser_tool import _get_page
        print("Opening LinkedIn login page — log in manually in the browser window.")
        print("Waiting up to 5 minutes for login to complete...")
        page = await _get_page(**browser_kwargs)
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)

        import asyncio as _asyncio
        deadline = 300  # 5 minutes
        interval = 5
        elapsed = 0
        while elapsed < deadline:
            try:
                await page.wait_for_selector(
                    "nav.global-nav, [class*='global-nav__me'], "
                    "[data-test-id='nav-settings__dropdown-trigger']",
                    timeout=interval * 1000,
                )
                return "[OK] Logged in to LinkedIn. Session saved. Set browser.headless: true in config/butler.yaml."
            except Exception:
                elapsed += interval
                remaining = deadline - elapsed
                if remaining > 0:
                    print(f"  Still waiting... ({remaining}s remaining)", flush=True)

        return "[ERROR] Login timeout — browser closed without detecting a successful login."

    # ── LinkedIn tools ────────────────────────────────────────────────────
    elif tool_name.startswith("linkedin_"):
        from butler.tools.linkedin_tool import (
            linkedin_get_feed,
            linkedin_get_notifications,
            linkedin_get_messages,
            linkedin_get_pages,
            linkedin_connect,
            linkedin_comment,
            linkedin_send_message,
            linkedin_post,
            linkedin_page_post,
        )

        if tool_name == "linkedin_get_feed":
            return await linkedin_get_feed(**browser_kwargs)
        elif tool_name == "linkedin_get_notifications":
            return await linkedin_get_notifications(**browser_kwargs)
        elif tool_name == "linkedin_get_messages":
            return await linkedin_get_messages(**browser_kwargs)
        elif tool_name == "linkedin_get_pages":
            return await linkedin_get_pages(**browser_kwargs)
        elif tool_name == "linkedin_connect":
            return await linkedin_connect(
                args["profile_url"], args.get("message", ""),
                approver=None, **browser_kwargs
            )
        elif tool_name == "linkedin_comment":
            return await linkedin_comment(
                args["post_url"], args["text"],
                approver=None, **browser_kwargs
            )
        elif tool_name == "linkedin_send_message":
            return await linkedin_send_message(
                args["recipient"], args["text"],
                approver=None, **browser_kwargs
            )
        elif tool_name == "linkedin_post":
            return await linkedin_post(
                args["text"], approver=None, **browser_kwargs
            )
        elif tool_name == "linkedin_page_post":
            return await linkedin_page_post(
                args["page_name"], args["text"],
                approver=None, **browser_kwargs
            )
        else:
            return f"[ERROR] Unknown LinkedIn tool: {tool_name}"

    else:
        return f"[ERROR] Unknown tool: {tool_name}\nAvailable: browser_navigate, browser_click, browser_type, browser_get_text, browser_screenshot, screenshot, file_read, file_write, file_list, email_list, email_read, email_send, linkedin_get_feed, linkedin_get_notifications, linkedin_get_messages, linkedin_get_pages, linkedin_connect, linkedin_comment, linkedin_send_message, linkedin_post, linkedin_page_post"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]

    # Parse JSON args (second arg) or default to empty dict
    if len(sys.argv) >= 3:
        try:
            args = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON args: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        args = {}

    # Set playwright browsers path
    script_dir = Path(__file__).parent.parent
    playwright_path = script_dir / ".playwright"
    if playwright_path.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(playwright_path))

    result = asyncio.run(_run(tool_name, args))
    print(result)


if __name__ == "__main__":
    main()
