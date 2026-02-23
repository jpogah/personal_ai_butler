"""LinkedIn automation tool using the persistent Playwright browser."""
from __future__ import annotations

import asyncio
import logging

from .browser_tool import _get_page

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _ensure_logged_in(page) -> bool:
    """Return True if LinkedIn session is active."""
    try:
        await page.wait_for_selector(
            "nav.global-nav, [data-test-id='nav-settings__dropdown-trigger'], "
            "[class*='global-nav__me']",
            timeout=6000,
        )
        return True
    except Exception:
        return False


_NOT_LOGGED_IN = (
    "[ERROR] Not logged in to LinkedIn. "
    "Set browser.headless: false in config/butler.yaml, run "
    "python3 -m butler.tools_cli linkedin_get_feed '{}', "
    "log in manually, then set headless: true again."
)


# ── read-only functions (SAFE) ────────────────────────────────────────────────

async def linkedin_get_feed(**kw) -> str:
    """Return the 10 most recent posts from the LinkedIn home feed."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        posts = await page.evaluate("""() => {
            function dedupName(s) {
                // LinkedIn renders names twice for accessibility; take first half if identical
                const t = s.trim();
                const mid = Math.floor(t.length / 2);
                if (mid > 2 && t.slice(0, mid).trim() === t.slice(mid).trim()) return t.slice(0, mid).trim();
                return t;
            }
            const results = [];
            for (const post of document.querySelectorAll('div.feed-shared-update-v2')) {
                if (results.length >= 10) break;

                // Author: .update-components-actor__title for real posts,
                // .update-components-feed-discovery-entity__text--body for suggestion cards
                let author = '';
                const actorTitle = post.querySelector('.update-components-actor__title');
                if (actorTitle) {
                    author = dedupName(actorTitle.innerText.split('\\u2022')[0].trim());
                } else {
                    const discEl = post.querySelector('.update-components-feed-discovery-entity__text--body');
                    if (discEl) author = dedupName(discEl.innerText.trim());
                }

                // Post text: inside .update-components-text, prefer span[dir=ltr]
                let text = '';
                const textContainer = post.querySelector('.update-components-text');
                if (textContainer) {
                    const ltr = textContainer.querySelector('span[dir="ltr"]');
                    text = (ltr || textContainer).innerText.trim().slice(0, 300);
                }

                if (author || text) results.push({author: author, text: text});
            }
            return results;
        }""")

        if not posts:
            return "[OK] No posts parsed (feed may be loading or layout changed). Try again in a moment."

        lines = []
        for i, p in enumerate(posts, 1):
            author = p.get("author", "Unknown")
            text = (p.get("text") or "").replace("\n", " ")
            lines.append(f"{i}. [{author}] {text}")
        return "\n".join(lines)

    except Exception as e:
        return f"[ERROR] linkedin_get_feed: {e}"


async def linkedin_get_notifications(**kw) -> str:
    """Return recent LinkedIn notifications."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.linkedin.com/notifications/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        notifs = await page.evaluate("""() => {
            function dedupText(s) {
                const t = s.trim();
                const mid = Math.floor(t.length / 2);
                if (mid > 5 && t.slice(0, mid).trim() === t.slice(mid).trim()) return t.slice(0, mid).trim();
                return t;
            }
            const results = [];
            for (const card of document.querySelectorAll('article.nt-card')) {
                if (results.length >= 10) break;
                // Prefer the span that limits to 3 lines — it's the clean summary text
                const spanEl = card.querySelector('span.nt-card__text--3-line');
                const linkEl = card.querySelector('a.nt-card__headline');
                const raw = spanEl ? spanEl.innerText.trim() : (linkEl ? linkEl.innerText.trim() : '');
                const cleaned = dedupText(raw.split('\\n').join(' ').replace(/  +/g, ' ')).slice(0, 200);
                if (cleaned) results.push(cleaned);
            }
            return results;
        }""")

        if not notifs:
            return "[OK] No notifications found (or layout changed)"

        return "\n".join(f"{i}. {n}" for i, n in enumerate(notifs, 1))

    except Exception as e:
        return f"[ERROR] linkedin_get_notifications: {e}"


async def linkedin_get_messages(**kw) -> str:
    """Return recent LinkedIn message threads (name + last-message snippet)."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        threads = await page.evaluate("""() => {
            const results = [];
            // ul.msg-conversations-container__conversations-list → li.scaffold-layout__list-item
            const list = document.querySelector('ul.msg-conversations-container__conversations-list');
            if (!list) return results;
            for (const li of list.querySelectorAll('li')) {
                if (results.length >= 10) break;
                // Participant name: inside the conversation card
                const nameEl = li.querySelector(
                    '[class*="msg-conversation-card__participant-names"], ' +
                    '[class*="conversation-person-name"], ' +
                    'h3, strong'
                );
                // Message snippet
                const snippetEl = li.querySelector(
                    '[class*="msg-conversation-card__message-snippet"], ' +
                    '[class*="last-activity"], ' +
                    'p, span[class*="message"]'
                );
                const name = nameEl ? nameEl.innerText.trim() : li.innerText.split('\\n')[0].trim();
                const snippet = snippetEl ? snippetEl.innerText.trim().slice(0, 100) : '';
                if (name && name.length > 1) results.push({name: name, snippet: snippet});
            }
            return results;
        }""")

        if not threads:
            return "[OK] No message threads found"

        # Filter out the empty-state placeholder LinkedIn injects when inbox is empty
        real = [t for t in threads if "no messages yet" not in t["name"].lower()]
        if not real:
            return "[OK] Inbox is empty"

        return "\n".join(
            f"{i}. {t['name']}: {t['snippet']}" for i, t in enumerate(real, 1)
        )

    except Exception as e:
        return f"[ERROR] linkedin_get_messages: {e}"


async def linkedin_get_pages(**kw) -> str:
    """Return LinkedIn pages the user manages."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.linkedin.com/company-admin/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        pages = await page.evaluate("""() => {
            const results = [];
            const seen = new Set();
            // Admin panel links for managed pages end with /admin/
            for (const l of document.querySelectorAll('a[href*="/company/"], a[href*="/showcase/"]')) {
                const name = l.innerText.trim();
                const href = l.href;
                if (!name || !href || name.length > 100) continue;
                // Prefer admin links; deduplicate by stripping /admin/ suffix for key
                const key = href.replace(/\\/admin\\/?$/, '').replace(/\\/$/, '');
                if (!seen.has(key)) {
                    seen.add(key);
                    results.push({name: name, url: href});
                }
            }
            return results.slice(0, 20);
        }""")

        if not pages:
            return "[OK] No managed pages found (or not on admin panel)"

        return "\n".join(f"{i}. {p['name']} — {p['url']}" for i, p in enumerate(pages, 1))

    except Exception as e:
        return f"[ERROR] linkedin_get_pages: {e}"


# ── MEDIUM-risk functions ─────────────────────────────────────────────────────

async def linkedin_connect(profile_url: str, message: str = "", **kw) -> str:
    """Send a LinkedIn connection request. Risk: MEDIUM."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "linkedin_connect",
            {"profile_url": profile_url, "message": message[:100]},
            RiskLevel.MEDIUM,
        )
        if not ok:
            return "[DENIED] Connection request cancelled."

    try:
        page = await _get_page(**kw)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Find the Connect button — LinkedIn nests it in different ways
        connect_selectors = [
            "button[aria-label*='Connect']",
            "button[aria-label*='connect']",
        ]
        clicked = False
        for sel in connect_selectors:
            try:
                await page.click(sel, timeout=5000)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            return "[ERROR] Could not find Connect button (may already be connected, or button is in 'More' menu)"

        await asyncio.sleep(1)

        if message:
            try:
                await page.click("button[aria-label='Add a note']", timeout=5000)
                await asyncio.sleep(0.5)
                await page.fill("textarea[name='message']", message, timeout=5000)
            except Exception:
                logger.debug("Could not add note to connection request — sending without note")

        # Confirm / send the request
        for sel in [
            "button[aria-label='Send now']",
            "button[aria-label='Send invitation']",
            "button:has-text('Send')",
            "button:has-text('Connect')",
        ]:
            try:
                await page.click(sel, timeout=5000)
                return f"[OK] Connection request sent to {profile_url}"
            except Exception:
                continue

        return "[OK] Connect button clicked — verify in LinkedIn if request was sent"

    except Exception as e:
        return f"[ERROR] linkedin_connect: {e}"


async def linkedin_comment(post_url: str, text: str, **kw) -> str:
    """Comment on a LinkedIn post. Risk: MEDIUM."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "linkedin_comment",
            {"post_url": post_url, "text": text[:200]},
            RiskLevel.MEDIUM,
        )
        if not ok:
            return "[DENIED] Comment cancelled."

    try:
        page = await _get_page(**kw)
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Activate the comment section
        for sel in [
            "button[aria-label*='comment']",
            "button[aria-label*='Comment']",
        ]:
            try:
                await page.click(sel, timeout=5000)
                break
            except Exception:
                continue

        await asyncio.sleep(0.5)

        # Find the contenteditable comment box
        editor_sel = (
            "div[contenteditable][aria-label*='text editor'], "
            "div[contenteditable][aria-placeholder*='comment'], "
            "div[contenteditable][aria-placeholder*='Comment'], "
            "div[contenteditable].ql-editor"
        )
        try:
            await page.click(editor_sel, timeout=5000)
            await page.fill(editor_sel, text, timeout=5000)
        except Exception:
            return "[ERROR] Could not find or fill comment editor"

        await asyncio.sleep(0.5)

        for sel in [
            "button[class*='comments-comment-box__submit-button']",
            "button[aria-label='Post comment']",
            "button:has-text('Post')",
        ]:
            try:
                await page.click(sel, timeout=5000)
                return f"[OK] Comment posted on {post_url}"
            except Exception:
                continue

        return "[ERROR] Could not find Post button for comment"

    except Exception as e:
        return f"[ERROR] linkedin_comment: {e}"


# ── HIGH-risk functions ───────────────────────────────────────────────────────

async def linkedin_send_message(recipient: str, text: str, **kw) -> str:
    """Send a LinkedIn DM. Risk: HIGH. recipient = name or profile URL."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "linkedin_send_message",
            {"recipient": recipient, "text": text[:200]},
            RiskLevel.HIGH,
        )
        if not ok:
            return "[DENIED] Message cancelled."

    try:
        page = await _get_page(**kw)

        if recipient.startswith("http"):
            # Profile URL — navigate there and click Message
            await page.goto(recipient, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            try:
                await page.click("button[aria-label*='Message']", timeout=8000)
            except Exception:
                return "[ERROR] Could not find Message button on profile page"
        else:
            # Name — use messaging compose
            await page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            try:
                await page.click(
                    "button[aria-label*='New message'], button[aria-label*='Compose'], "
                    "a[href*='new-conversation']",
                    timeout=8000,
                )
                await asyncio.sleep(0.5)
                await page.fill(
                    "input[aria-label*='Search'], input[placeholder*='Search'],"
                    "input[placeholder*='Type a name']",
                    recipient,
                    timeout=5000,
                )
                await asyncio.sleep(1)
                await page.click("li[class*='compose-typeahead-result']", timeout=5000)
                await asyncio.sleep(0.5)
                try:
                    await page.click("button:has-text('Next'), button[aria-label*='Next']", timeout=3000)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            except Exception as e:
                return f"[ERROR] Could not open compose for '{recipient}': {e}"

        await asyncio.sleep(1)

        # Type the message
        msg_sel = (
            "div[class*='msg-form__contenteditable'][contenteditable], "
            "div[contenteditable][aria-label*='Write a message'], "
            "div[contenteditable][aria-label*='message']"
        )
        try:
            await page.click(msg_sel, timeout=5000)
            await page.fill(msg_sel, text, timeout=5000)
        except Exception:
            return "[ERROR] Could not type into message field"

        # Send via keyboard (most reliable) then button fallback
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        try:
            await page.click(
                "button[class*='msg-form__send-button'], button[aria-label*='Send']",
                timeout=3000,
            )
        except Exception:
            pass

        return f"[OK] Message sent to {recipient}"

    except Exception as e:
        return f"[ERROR] linkedin_send_message: {e}"


async def linkedin_post(text: str, **kw) -> str:
    """Publish a personal LinkedIn post. Risk: HIGH."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "linkedin_post", {"text": text[:300]}, RiskLevel.HIGH
        )
        if not ok:
            return "[DENIED] Post cancelled."

    try:
        page = await _get_page(**kw)
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Open the post composer
        for sel in [
            "button[aria-placeholder*='Start a post']",
            "button:has-text('Start a post')",
            "[class*='share-box-feed-entry__trigger']",
        ]:
            try:
                await page.click(sel, timeout=5000)
                break
            except Exception:
                continue

        await asyncio.sleep(1)

        # Fill in the editor modal
        editor_sel = (
            "div[class*='ql-editor'][contenteditable], "
            "div[contenteditable][aria-placeholder*='What do you want to talk about'], "
            "div[contenteditable]"
        )
        try:
            await page.click(editor_sel, timeout=5000)
            await page.fill(editor_sel, text, timeout=5000)
        except Exception:
            return "[ERROR] Could not open or fill post editor"

        await asyncio.sleep(0.5)

        for sel in [
            "button[class*='share-actions__primary-action']",
            "button[aria-label*='Post']",
            "button:has-text('Post')",
        ]:
            try:
                await page.click(sel, timeout=5000)
                return "[OK] Post published to LinkedIn"
            except Exception:
                continue

        return "[ERROR] Could not find Post button"

    except Exception as e:
        return f"[ERROR] linkedin_post: {e}"


async def linkedin_page_post(page_name: str, text: str, **kw) -> str:
    """Publish a post as a managed LinkedIn page. Risk: HIGH.
    page_name = URL slug (e.g. 'my-company') or full admin URL.
    """
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "linkedin_page_post",
            {"page_name": page_name, "text": text[:300]},
            RiskLevel.HIGH,
        )
        if not ok:
            return "[DENIED] Page post cancelled."

    try:
        page = await _get_page(**kw)

        if page_name.startswith("http"):
            admin_url = page_name.rstrip("/") + "/admin/"
        else:
            admin_url = f"https://www.linkedin.com/company/{page_name}/admin/"

        await page.goto(admin_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        for sel in [
            "button:has-text('Create a post')",
            "button:has-text('Start a post')",
            "[class*='share-box-feed-entry__trigger']",
        ]:
            try:
                await page.click(sel, timeout=5000)
                break
            except Exception:
                continue

        await asyncio.sleep(1)

        editor_sel = (
            "div[class*='ql-editor'][contenteditable], "
            "div[contenteditable][aria-placeholder*='What do you want to talk about'], "
            "div[contenteditable]"
        )
        try:
            await page.click(editor_sel, timeout=5000)
            await page.fill(editor_sel, text, timeout=5000)
        except Exception:
            return "[ERROR] Could not open or fill post editor on page admin"

        await asyncio.sleep(0.5)

        for sel in [
            "button[class*='share-actions__primary-action']",
            "button:has-text('Post')",
            "button:has-text('Publish')",
        ]:
            try:
                await page.click(sel, timeout=5000)
                return f"[OK] Post published as page '{page_name}'"
            except Exception:
                continue

        return "[ERROR] Could not find Post/Publish button on page admin"

    except Exception as e:
        return f"[ERROR] linkedin_page_post: {e}"
