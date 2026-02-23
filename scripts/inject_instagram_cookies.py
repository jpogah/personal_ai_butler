"""
Inject Instagram cookies extracted from MCP browser into butler's persistent profile.
Run once after extracting cookies:
    python3 scripts/inject_instagram_cookies.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

COOKIES_FILE = ROOT / "data" / "instagram_cookies.json"
PROFILE_DIR = ROOT / "data" / "browser_profile"
PLAYWRIGHT_PATH = ROOT / ".playwright"


async def main():
    if not COOKIES_FILE.exists():
        print(f"[ERROR] Cookies file not found: {COOKIES_FILE}")
        sys.exit(1)

    cookies = json.loads(COOKIES_FILE.read_text())
    print(f"Loaded {len(cookies)} cookies from {COOKIES_FILE}")

    if PLAYWRIGHT_PATH.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_PATH))

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Add cookies before navigating
        await ctx.add_cookies(cookies)
        print("Cookies injected into profile.")

        # Verify by navigating to Instagram
        print("Verifying session...")
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
        url = page.url
        title = await page.title()
        print(f"  URL:   {url}")
        print(f"  Title: {title}")

        if "accounts/login" in url:
            print("[WARN] Still on login page — cookies may not have worked.")
        else:
            print("[OK] Logged in! Session saved to browser profile.")

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
