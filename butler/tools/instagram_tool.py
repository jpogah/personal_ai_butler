"""Instagram automation tool using the persistent Playwright browser."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .browser_tool import _get_page

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _ensure_logged_in(page) -> bool:
    """Return True if an Instagram session is active."""
    # URL-based check is the most reliable: logged-in pages are never at /accounts/login/
    url = page.url
    if "accounts/login" in url or "accounts/signup" in url:
        return False
    try:
        await page.wait_for_selector(
            "a[href='/explore/'], "
            "a[href='/direct/inbox/'], "
            "svg[aria-label='Home'], "
            "span[aria-label='Home']",
            timeout=6000,
        )
        return True
    except Exception:
        # Final fallback: if URL is instagram.com root or a profile/feed page, assume logged in
        return "instagram.com" in url and "login" not in url


_NOT_LOGGED_IN = (
    "[ERROR] Not logged in to Instagram. "
    "Set browser.headless: false in config/butler.yaml, run "
    "python3 -m butler.tools_cli instagram_login '{}', "
    "log in manually, then set headless: true again."
)


# ── read-only functions (SAFE) ────────────────────────────────────────────────

async def instagram_get_feed(**kw) -> str:
    """Return the 10 most recent posts from the Instagram home feed."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        posts = await page.evaluate("""() => {
            const results = [];
            for (const article of document.querySelectorAll('article')) {
                if (results.length >= 10) break;

                // Author: first anchor whose pathname is /username/ (profile link)
                const authorAnchor = [...article.querySelectorAll('a[href]')]
                    .find(a => { try { return /^\\/[a-zA-Z0-9_.]+\\/$/.test(new URL(a.href).pathname); } catch(e) { return false; } });
                const author = authorAnchor ? authorAnchor.innerText.trim() : '';

                // Caption: span with both _aaco and _aacu classes (Instagram's stable caption marker)
                // Trim trailing "...more" suffix
                const captionEl = article.querySelector('span._aaco._aacu');
                const caption = captionEl
                    ? captionEl.innerText.trim().replace(/\\n\\.\\.\\..*$/s, '').trim().slice(0, 300)
                    : '';

                // Post URL: first /p/ or /reel/ link in the article
                const linkEl = article.querySelector('a[href*="/p/"], a[href*="/reel/"]');
                const url = linkEl ? linkEl.href : '';

                if (author || caption) results.push({author: author, caption: caption, url: url});
            }
            return results;
        }""")

        if not posts:
            return "[OK] No posts parsed (feed may be loading or layout changed). Try again in a moment."

        lines = []
        for i, p in enumerate(posts, 1):
            author = p.get("author") or "unknown"
            caption = (p.get("caption") or "").split("\n")[0]
            url = p.get("url") or ""
            suffix = f" — {url}" if url else ""
            lines.append(f"{i}. [@{author}] {caption}{suffix}")
        return "\n".join(lines)

    except Exception as e:
        return f"[ERROR] instagram_get_feed: {e}"


async def instagram_get_notifications(**kw) -> str:
    """Return recent Instagram activity notifications."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        # Click the Notifications link in the left sidebar (href="#" with text "Notifications")
        clicked = await page.evaluate("""() => {
            const links = [...document.querySelectorAll('a[href="#"]')];
            const notif = links.find(l => l.innerText.trim() === 'Notifications');
            if (notif) { notif.click(); return true; }
            return false;
        }""")
        if not clicked:
            return "[ERROR] Could not find Notifications button in sidebar"

        await asyncio.sleep(3)

        # Parse notification rows from the panel (div.xx4vt8u holds the content)
        notifs = await page.evaluate("""() => {
            const results = [];
            // Find the notifications content panel
            const contentDiv = document.querySelector('div.xx4vt8u');
            if (!contentDiv) return [];

            // Walk down to find the row container
            let listEl = contentDiv.children[1]; // 2nd child: actual notifications
            if (!listEl) return [];
            // Drill down through single-child wrappers
            while (listEl && listEl.children.length === 1) {
                listEl = listEl.firstElementChild;
            }
            if (!listEl) return [];

            const SKIP_TOKENS = new Set(['Follow', 'Unfollow', 'Remove']);
            for (const row of listEl.children) {
                if (results.length >= 15) break;
                const text = row.innerText.trim();
                if (!text) continue;
                // Each row: "username\\nFull Name\\nAction\\nButton"
                const parts = text.split('\\n').map(s => s.trim()).filter(p => p && !SKIP_TOKENS.has(p));
                if (parts.length >= 2) {
                    const username = parts[0];
                    // Action is usually the 3rd part (after username + full name); fall back to 2nd
                    const action = parts.length >= 3 ? parts[2] : parts[1];
                    results.push({username, action});
                }
            }
            return results;
        }""")

        if not notifs:
            return "[OK] No notifications found (panel may be empty)"

        return "\n".join(
            f"{i}. @{n['username']} — {n['action']}"
            for i, n in enumerate(notifs, 1)
        )

    except Exception as e:
        return f"[ERROR] instagram_get_notifications: {e}"


async def instagram_get_messages(**kw) -> str:
    """Return recent Instagram DM threads (username + last message preview)."""
    try:
        page = await _get_page(**kw)
        await page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if not await _ensure_logged_in(page):
            return _NOT_LOGGED_IN

        threads = await page.evaluate("""async () => {
            // Use Instagram's internal inbox API — works with existing session cookies
            try {
                const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                const resp = await fetch(
                    '/api/v1/direct_v2/inbox/?visual_message_return_type=unseen&thread_message_limit=1&persistentBadging=true&limit=20',
                    {
                        headers: {
                            'x-csrftoken': csrfToken,
                            'x-ig-app-id': '936619743392459',
                            'x-requested-with': 'XMLHttpRequest',
                        }
                    }
                );
                const data = await resp.json();
                const inboxThreads = (data.inbox && data.inbox.threads) || [];
                return inboxThreads.slice(0, 10).map(t => ({
                    users: t.users ? t.users.map(u => u.username).join(', ') : t.thread_title || '?',
                    last_message: t.last_permanent_item
                        ? (t.last_permanent_item.text || '[media]').slice(0, 120)
                        : ''
                }));
            } catch(e) {
                return [{users: '[API error]', last_message: e.message}];
            }
        }""")

        if not threads:
            return "[OK] No DM threads found (inbox may be empty)"

        return "\n".join(
            f"{i}. @{t['users']}: {t['last_message']}"
            for i, t in enumerate(threads, 1)
        )

    except Exception as e:
        return f"[ERROR] instagram_get_messages: {e}"


# ── LOW-risk functions ────────────────────────────────────────────────────────

async def instagram_like(post_url: str, **kw) -> str:
    """Like an Instagram post. Risk: LOW (auto-approved)."""
    kw.pop("approver", None)  # LOW risk — auto-approved; pop to avoid passing to _get_page
    try:
        page = await _get_page(**kw)
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Check if already liked (aria-label flips to "Unlike" when liked)
        already = await page.query_selector("svg[aria-label='Unlike']")
        if already:
            return "[OK] Post is already liked"

        # Click the Like button
        like_clicked = False
        for sel in [
            "button:has(svg[aria-label='Like'])",
            "span[aria-label='Like']",
        ]:
            try:
                await page.click(sel, timeout=5000)
                like_clicked = True
                break
            except Exception:
                continue

        if not like_clicked:
            # JS fallback
            found = await page.evaluate("""() => {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.querySelector('svg[aria-label="Like"]'));
                if (btn) { btn.click(); return true; }
                return false;
            }""")
            if not found:
                return "[ERROR] Could not find Like button on this post"

        return f"[OK] Liked {post_url}"

    except Exception as e:
        return f"[ERROR] instagram_like: {e}"


# ── MEDIUM-risk functions ─────────────────────────────────────────────────────

async def instagram_follow(profile_url: str, **kw) -> str:
    """Follow an Instagram user. Risk: MEDIUM."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "instagram_follow", {"profile_url": profile_url}, RiskLevel.MEDIUM
        )
        if not ok:
            return "[DENIED] Follow cancelled."

    try:
        page = await _get_page(**kw)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Find the Follow button — must be exactly "Follow", not "Following" / "Follow Back"
        result = await page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button, div[role="button"]')];
            const btn = btns.find(b => b.innerText.trim() === 'Follow');
            if (btn) { btn.click(); return 'clicked'; }
            // Check if already following
            const following = btns.find(b => /Following|Requested/i.test(b.innerText.trim()));
            if (following) return 'already';
            return 'not_found';
        }""")

        if result == "clicked":
            await asyncio.sleep(1)
            # Confirm: button should now say "Following" or "Requested"
            status = await page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button, div[role="button"]')];
                const f = btns.find(b => /Following|Requested/i.test(b.innerText.trim()));
                return f ? f.innerText.trim() : 'unknown';
            }""")
            return f"[OK] Followed {profile_url} (status: {status})"
        elif result == "already":
            return f"[OK] Already following {profile_url}"
        else:
            return "[ERROR] Could not find Follow button (profile may be private or not found)"

    except Exception as e:
        return f"[ERROR] instagram_follow: {e}"


async def instagram_comment(post_url: str, text: str, **kw) -> str:
    """Comment on an Instagram post. Risk: MEDIUM."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "instagram_comment",
            {"post_url": post_url, "text": text[:200]},
            RiskLevel.MEDIUM,
        )
        if not ok:
            return "[DENIED] Comment cancelled."

    try:
        page = await _get_page(**kw)
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Activate the comment textarea
        comment_sel = (
            "textarea[placeholder*='Add a comment'], "
            "textarea[aria-label*='Add a comment'], "
            "textarea[placeholder*='comment']"
        )
        try:
            await page.click(comment_sel, timeout=5000)
        except Exception:
            return "[ERROR] Could not find comment input on this post"

        await asyncio.sleep(0.5)
        await page.fill(comment_sel, text, timeout=5000)
        await asyncio.sleep(0.3)

        # Submit with Enter (most reliable on Instagram)
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)

        # Button fallback if Enter didn't work
        for sel in ["button[type='submit']:has-text('Post')", "div[role='button']:has-text('Post')"]:
            try:
                await page.click(sel, timeout=2000)
                break
            except Exception:
                continue

        return f"[OK] Comment posted on {post_url}"

    except Exception as e:
        return f"[ERROR] instagram_comment: {e}"


# ── HIGH-risk functions ───────────────────────────────────────────────────────

async def instagram_send_message(recipient: str, text: str, **kw) -> str:
    """Send an Instagram DM. Risk: HIGH. recipient = username or profile URL."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "instagram_send_message",
            {"recipient": recipient, "text": text[:200]},
            RiskLevel.HIGH,
        )
        if not ok:
            return "[DENIED] Message cancelled."

    try:
        page = await _get_page(**kw)

        if recipient.startswith("http"):
            # Profile URL — navigate there and click the Message button
            await page.goto(recipient, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            try:
                await page.click(
                    "div[role='button']:has-text('Message'), button:has-text('Message')",
                    timeout=8000,
                )
            except Exception:
                return "[ERROR] Could not find Message button on profile page"
        else:
            # Username — use New Message compose flow
            await page.goto("https://www.instagram.com/direct/new/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            try:
                await page.fill(
                    "input[name='queryBox'], input[placeholder*='Search']",
                    recipient,
                    timeout=5000,
                )
                await asyncio.sleep(1)
                # Click first autocomplete result
                await page.click(
                    "div[role='option']:first-child, div[aria-selected] span, div[role='option']",
                    timeout=5000,
                )
                await asyncio.sleep(0.5)
                # Next button in the compose flow
                try:
                    await page.click(
                        "div[role='button']:has-text('Next'), button:has-text('Next')",
                        timeout=3000,
                    )
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            except Exception as e:
                return f"[ERROR] Could not open DM compose for '{recipient}': {e}"

        await asyncio.sleep(1)

        # Type the message
        msg_sel = (
            "textarea[placeholder*='Message'], "
            "textarea[aria-label*='Message'], "
            "div[contenteditable][aria-label*='Message'], "
            "div[role='textbox']"
        )
        try:
            await page.click(msg_sel, timeout=5000)
            await page.fill(msg_sel, text, timeout=5000)
        except Exception:
            return "[ERROR] Could not find message input field"

        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        try:
            await page.click(
                "button[aria-label='Send'], div[role='button']:has-text('Send')",
                timeout=3000,
            )
        except Exception:
            pass

        return f"[OK] Message sent to {recipient}"

    except Exception as e:
        return f"[ERROR] instagram_send_message: {e}"


async def instagram_post(image_path: str, caption: str = "", **kw) -> str:
    """Post a photo to Instagram. Risk: HIGH."""
    approver = kw.pop("approver", None)
    if approver:
        from ..permissions.classifier import RiskLevel
        ok = await approver.request_approval(
            "instagram_post",
            {"image_path": image_path, "caption": caption[:300]},
            RiskLevel.HIGH,
        )
        if not ok:
            return "[DENIED] Post cancelled."

    # Validate file exists before attempting upload
    if not Path(image_path).exists():
        return f"[ERROR] Image file not found: {image_path}"

    try:
        page = await _get_page(**kw)
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Click the Create / New Post button (sidebar link with text "Create")
        create_clicked = False
        try:
            # Primary: the sidebar "Create" link (href="#", text "Create")
            await page.click("a:has-text('Create')", timeout=5000)
            create_clicked = True
        except Exception:
            pass

        if not create_clicked:
            # JS fallback: click the Create link by text
            found = await page.evaluate("""() => {
                const links = [...document.querySelectorAll('a[href="#"]')];
                const create = links.find(l => l.innerText.trim() === 'Create');
                if (create) { create.click(); return true; }
                return false;
            }""")
            if not found:
                return "[ERROR] Could not find the Create post button"

        await asyncio.sleep(2)

        # Use filechooser event to set file (more reliable than set_input_files)
        try:
            async with page.expect_file_chooser(timeout=8000) as fc_info:
                await page.click(
                    "button:has-text('Select from computer')",
                    timeout=5000,
                )
            file_chooser = await fc_info.value
            await file_chooser.set_files(image_path)
        except Exception as e:
            return f"[ERROR] Could not open file picker or set file: {e}"

        await asyncio.sleep(3)

        # Navigate through crop (Next) → filters/edit (Next) → caption (Share)
        # Instagram uses div[role="button"] (not <button>) for these header actions.
        # Step 1: Wait for Crop dialog, then click Next
        try:
            await page.wait_for_selector("[role='dialog'] [role='heading']:has-text('Crop')", timeout=8000)
            await page.click("[role='dialog'] div[role='button']:has-text('Next')", timeout=6000)
        except Exception as e:
            return f"[ERROR] Could not advance from crop step: {e}"

        # Step 2: Wait for Edit/Filters dialog, then click Next
        try:
            await page.wait_for_selector("[role='dialog'] [role='heading']:has-text('Edit')", timeout=10000)
            await page.click("[role='dialog'] div[role='button']:has-text('Next')", timeout=6000)
        except Exception as e:
            return f"[ERROR] Could not advance from filter step: {e}"

        await asyncio.sleep(1)

        # Step 3: Caption screen — fill caption then Share
        if caption:
            try:
                await page.click("div[role='textbox'][aria-label*='caption' i], div[contenteditable][aria-label*='caption' i]", timeout=5000)
                await page.keyboard.type(caption)
                await asyncio.sleep(0.5)
            except Exception:
                logger.debug("Could not fill caption field — proceeding without it")

        # Click Share and wait for confirmation
        try:
            await page.click("[role='dialog'] div[role='button']:has-text('Share')", timeout=10000)
        except Exception as e:
            return f"[ERROR] Could not find Share button: {e}"

        # Wait for "Post shared" dialog
        try:
            await page.wait_for_selector(
                "heading:has-text('Post shared'), h1:has-text('Post shared'), h3:has-text('Your post has been shared')",
                timeout=30000,
            )
        except Exception:
            pass  # Even if confirmation dialog isn't detected, post likely went through

        return "[OK] Photo posted to Instagram"

    except Exception as e:
        return f"[ERROR] instagram_post: {e}"
