"""Tool definitions (JSON schema) for Claude API tool_use + dispatcher."""
from __future__ import annotations

import logging
from typing import Optional, Callable, Awaitable, Any

from ..permissions.approval import ApprovalManager

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    pass


# ─── Tool schema definitions ──────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": "Run a shell command on the Mac. Output is returned as text. Use for file operations, running scripts, checking system status, etc. Dangerous commands will require user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "number", "description": "Timeout in seconds (default 30)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "file_read",
        "description": "Read the contents of a file on the Mac.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or ~ path to the file"},
                "max_bytes": {"type": "integer", "description": "Max bytes to read (default 100000)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_write",
        "description": "Write or overwrite a file on the Mac. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or ~ path to write to"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "file_list",
        "description": "List files and directories in a folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Path to directory"},
                "show_hidden": {"type": "boolean", "description": "Include hidden files (default false)"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "file_send",
        "description": "Send a file to the user directly in chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to send"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "browser_navigate",
        "description": "Open a URL in the browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL including https://"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current browser page using a CSS selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector or text to click"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_type",
        "description": "Type text into a field on the current browser page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the input field"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Get text content from the current browser page or a specific element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector (default: body = full page)"},
            },
        },
    },
    {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current browser page and send it to the user.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the full Mac desktop.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["browser", "desktop"],
                    "description": "What to screenshot: current browser page or full desktop",
                },
            },
        },
    },
    {
        "name": "email_list",
        "description": "List recent emails from the inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of emails to list (default 10)"},
                "folder": {"type": "string", "description": "Mailbox folder (default INBOX)"},
                "account": {"type": "string", "description": "Email account name (e.g. 'personal', 'work'). Omit to use default."},
            },
        },
    },
    {
        "name": "email_read",
        "description": "Read the full content of a specific email by its message ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Email message ID from email_list"},
                "account": {"type": "string", "description": "Email account name. Omit to use default."},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "email_send",
        "description": "Send an email. Always requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text)"},
                "account": {"type": "string", "description": "Email account to send from (e.g. 'personal', 'work'). Omit to use default."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "linkedin_get_feed",
        "description": "Fetch the 10 most recent posts from the LinkedIn home feed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "linkedin_get_notifications",
        "description": "Fetch recent LinkedIn notifications.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "linkedin_get_messages",
        "description": "Fetch recent LinkedIn message threads (name + preview).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "linkedin_get_pages",
        "description": "List LinkedIn pages managed by the user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "linkedin_connect",
        "description": "Send a LinkedIn connection request to a profile. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "profile_url": {"type": "string", "description": "Full LinkedIn profile URL"},
                "message": {"type": "string", "description": "Optional personal note (max 300 chars)"},
            },
            "required": ["profile_url"],
        },
    },
    {
        "name": "linkedin_comment",
        "description": "Post a comment on a LinkedIn post. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_url": {"type": "string", "description": "Full URL of the LinkedIn post"},
                "text": {"type": "string", "description": "Comment text"},
            },
            "required": ["post_url", "text"],
        },
    },
    {
        "name": "linkedin_send_message",
        "description": "Send a LinkedIn direct message. Requires user approval. recipient = full name or profile URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Full name or LinkedIn profile URL"},
                "text": {"type": "string", "description": "Message body"},
            },
            "required": ["recipient", "text"],
        },
    },
    {
        "name": "linkedin_post",
        "description": "Publish a personal update/post on LinkedIn. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Post text content"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "linkedin_page_post",
        "description": "Publish a post as a managed LinkedIn page. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_name": {"type": "string", "description": "Page URL slug (e.g. 'my-company') or full admin URL"},
                "text": {"type": "string", "description": "Post text content"},
            },
            "required": ["page_name", "text"],
        },
    },
    {
        "name": "instagram_get_feed",
        "description": "Fetch the 10 most recent posts from the Instagram home feed.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "instagram_get_notifications",
        "description": "Fetch recent Instagram activity/notifications.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "instagram_get_messages",
        "description": "Fetch recent Instagram DM threads (username + message preview).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "instagram_follow",
        "description": "Follow an Instagram user. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "profile_url": {"type": "string", "description": "Full Instagram profile URL"},
            },
            "required": ["profile_url"],
        },
    },
    {
        "name": "instagram_like",
        "description": "Like an Instagram post. Auto-approved (low risk).",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_url": {"type": "string", "description": "Full Instagram post URL"},
            },
            "required": ["post_url"],
        },
    },
    {
        "name": "instagram_comment",
        "description": "Post a comment on an Instagram post. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "post_url": {"type": "string", "description": "Full URL of the Instagram post"},
                "text": {"type": "string", "description": "Comment text"},
            },
            "required": ["post_url", "text"],
        },
    },
    {
        "name": "instagram_send_message",
        "description": "Send an Instagram DM. Always requires user approval. recipient = username or profile URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Instagram username or full profile URL"},
                "text": {"type": "string", "description": "Message body"},
            },
            "required": ["recipient", "text"],
        },
    },
    {
        "name": "instagram_post",
        "description": "Post a photo to Instagram. Always requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute path to the image file"},
                "caption": {"type": "string", "description": "Optional caption text"},
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a fact about the user to persistent memory. Use this when the user asks you to "
            "remember something, or when you learn something important and stable about them "
            "(preferences, project paths, recurring tasks, name, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short label for the fact (e.g. 'main_project_path', 'preferred_language')"},
                "value": {"type": "string", "description": "The fact to remember"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget",
        "description": "Remove a previously remembered fact from memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to forget"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "list_memories",
        "description": "Show all facts currently stored in memory about the user.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt using Stability AI. "
            "Returns the saved image file path (which is then automatically sent to the user). "
            "Use this to create photos, illustrations, artwork, or any visual content. "
            "Generated images can also be passed to instagram_post or file_send."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed text description of the image to generate",
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": (
                        "Image dimensions: '1:1' (square, default), '16:9' (widescreen), "
                        "'9:16' (portrait/Stories), '4:3', '3:4'"
                    ),
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"],
                },
                "style_preset": {
                    "type": "string",
                    "description": (
                        "Optional art style: photographic, digital-art, anime, cinematic, "
                        "comic-book, fantasy-art, line-art, neon-punk, pixel-art, 3d-model"
                    ),
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Things to exclude from the image (optional)",
                },
            },
            "required": ["prompt"],
        },
    },
]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

class ToolRegistry:
    """Holds tool implementations and dispatches calls."""

    def __init__(self):
        self._bash_fn = None
        self._file_read_fn = None
        self._file_write_fn = None
        self._file_list_fn = None
        self._browser_cfg: dict = {}
        self._email_tools: dict = {}   # account_name → EmailTool
        self._send_file_to_user: Optional[Callable] = None
        self._approver_factory: Optional[Callable] = None
        self._history = None   # ConversationHistory instance for memory tools
        self._stability_api_key: str = ""

    def set_stability_key(self, api_key: str) -> None:
        self._stability_api_key = api_key

    def configure(
        self,
        bash_fn,
        file_read_fn,
        file_write_fn,
        file_list_fn,
        file_send_fn,          # accepted but unused (kept for API compat)
        browser_cfg: dict,
        email_tools,           # dict[str, EmailTool] or single EmailTool (legacy)
        send_file_to_user: Callable,
        approver_factory: Callable,
    ):
        self._bash_fn = bash_fn
        self._file_read_fn = file_read_fn
        self._file_write_fn = file_write_fn
        self._file_list_fn = file_list_fn
        self._browser_cfg = browser_cfg
        # Accept both dict (multi-account) and single EmailTool (legacy)
        if isinstance(email_tools, dict):
            self._email_tools = email_tools
        elif email_tools is not None:
            self._email_tools = {"default": email_tools}
        else:
            self._email_tools = {}
        self._send_file_to_user = send_file_to_user
        self._approver_factory = approver_factory

    def _get_email_tool(self, account: Optional[str] = None):
        """Return the EmailTool for the given account name, or the default."""
        if not self._email_tools:
            return None
        if account and account in self._email_tools:
            return self._email_tools[account]
        return next(iter(self._email_tools.values()))

    def set_history(self, history) -> None:
        self._history = history

    async def dispatch(
        self,
        tool_name: str,
        args: dict,
        sender_id: str,
        channel: str,
        recipient_id: str,
    ) -> str:
        approver: Optional[ApprovalManager] = None
        if self._approver_factory:
            approver = self._approver_factory(sender_id)

        bk = self._browser_cfg

        if tool_name == "bash":
            return await self._bash_fn(
                args["command"],
                approver,
                timeout=args.get("timeout", 30.0),
            )

        elif tool_name == "file_read":
            return await self._file_read_fn(
                args["path"],
                max_bytes=args.get("max_bytes", 100_000),
            )

        elif tool_name == "file_write":
            return await self._file_write_fn(
                args["path"],
                args["content"],
                approver,
            )

        elif tool_name == "file_list":
            return await self._file_list_fn(
                args["directory"],
                show_hidden=args.get("show_hidden", False),
            )

        elif tool_name == "file_send":
            path = args["path"]
            await self._send_file_to_user(recipient_id, path, channel)
            return f"[OK] Sent {path} to user"

        elif tool_name == "browser_navigate":
            from ..tools.browser_tool import browser_navigate
            return await browser_navigate(args["url"], **bk)

        elif tool_name == "browser_click":
            from ..tools.browser_tool import browser_click
            return await browser_click(args["selector"], **bk)

        elif tool_name == "browser_type":
            from ..tools.browser_tool import browser_type
            return await browser_type(args["selector"], args["text"], **bk)

        elif tool_name == "browser_get_text":
            from ..tools.browser_tool import browser_get_text
            return await browser_get_text(args.get("selector", "body"), **bk)

        elif tool_name == "browser_screenshot":
            from ..tools.browser_tool import browser_screenshot
            path = await browser_screenshot(**bk)
            if not path.startswith("[ERROR]"):
                await self._send_file_to_user(recipient_id, path, channel)
                return f"[OK] Screenshot sent"
            return path

        elif tool_name == "screenshot":
            from ..tools.screenshot_tool import take_screenshot
            target = args.get("target", "desktop")
            path = await take_screenshot(target=target, browser_kwargs=bk)
            if not path.startswith("[ERROR]"):
                await self._send_file_to_user(recipient_id, path, channel)
                return f"[OK] {target} screenshot sent"
            return path

        elif tool_name == "email_list":
            et = self._get_email_tool(args.get("account"))
            if not et:
                return "[ERROR] Email not configured"
            return await et.list_emails(
                count=args.get("count", 10),
                folder=args.get("folder", "INBOX"),
            )

        elif tool_name == "email_read":
            et = self._get_email_tool(args.get("account"))
            if not et:
                return "[ERROR] Email not configured"
            return await et.read_email(args["message_id"])

        elif tool_name == "email_send":
            et = self._get_email_tool(args.get("account"))
            if not et:
                return "[ERROR] Email not configured"
            return await et.send_email(
                args["to"], args["subject"], args["body"], approver
            )

        elif tool_name == "linkedin_get_feed":
            from ..tools.linkedin_tool import linkedin_get_feed
            return await linkedin_get_feed(**bk)

        elif tool_name == "linkedin_get_notifications":
            from ..tools.linkedin_tool import linkedin_get_notifications
            return await linkedin_get_notifications(**bk)

        elif tool_name == "linkedin_get_messages":
            from ..tools.linkedin_tool import linkedin_get_messages
            return await linkedin_get_messages(**bk)

        elif tool_name == "linkedin_get_pages":
            from ..tools.linkedin_tool import linkedin_get_pages
            return await linkedin_get_pages(**bk)

        elif tool_name == "linkedin_connect":
            from ..tools.linkedin_tool import linkedin_connect
            return await linkedin_connect(
                args["profile_url"], args.get("message", ""), approver=approver, **bk
            )

        elif tool_name == "linkedin_comment":
            from ..tools.linkedin_tool import linkedin_comment
            return await linkedin_comment(
                args["post_url"], args["text"], approver=approver, **bk
            )

        elif tool_name == "linkedin_send_message":
            from ..tools.linkedin_tool import linkedin_send_message
            return await linkedin_send_message(
                args["recipient"], args["text"], approver=approver, **bk
            )

        elif tool_name == "linkedin_post":
            from ..tools.linkedin_tool import linkedin_post
            return await linkedin_post(args["text"], approver=approver, **bk)

        elif tool_name == "linkedin_page_post":
            from ..tools.linkedin_tool import linkedin_page_post
            return await linkedin_page_post(
                args["page_name"], args["text"], approver=approver, **bk
            )

        elif tool_name == "instagram_get_feed":
            from ..tools.instagram_tool import instagram_get_feed
            return await instagram_get_feed(**bk)

        elif tool_name == "instagram_get_notifications":
            from ..tools.instagram_tool import instagram_get_notifications
            return await instagram_get_notifications(**bk)

        elif tool_name == "instagram_get_messages":
            from ..tools.instagram_tool import instagram_get_messages
            return await instagram_get_messages(**bk)

        elif tool_name == "instagram_follow":
            from ..tools.instagram_tool import instagram_follow
            return await instagram_follow(args["profile_url"], approver=approver, **bk)

        elif tool_name == "instagram_like":
            from ..tools.instagram_tool import instagram_like
            return await instagram_like(args["post_url"], approver=approver, **bk)

        elif tool_name == "instagram_comment":
            from ..tools.instagram_tool import instagram_comment
            return await instagram_comment(
                args["post_url"], args["text"], approver=approver, **bk
            )

        elif tool_name == "instagram_send_message":
            from ..tools.instagram_tool import instagram_send_message
            return await instagram_send_message(
                args["recipient"], args["text"], approver=approver, **bk
            )

        elif tool_name == "instagram_post":
            from ..tools.instagram_tool import instagram_post
            return await instagram_post(
                args["image_path"], args.get("caption", ""), approver=approver, **bk
            )

        elif tool_name == "remember":
            if not self._history:
                return "[ERROR] Memory not available"
            await self._history.save_memory(sender_id, channel, args["key"], args["value"])
            return f"✅ Remembered: {args['key']} = {args['value']}"

        elif tool_name == "forget":
            if not self._history:
                return "[ERROR] Memory not available"
            removed = await self._history.forget_memory(sender_id, channel, args["key"])
            return f"✅ Forgotten: {args['key']}" if removed else f"Nothing stored under '{args['key']}'"

        elif tool_name == "list_memories":
            if not self._history:
                return "[ERROR] Memory not available"
            memories = await self._history.list_memories(sender_id, channel)
            if not memories:
                return "No memories stored yet."
            return "\n".join(f"• {k}: {v}" for k, v in memories.items())

        elif tool_name == "generate_image":
            from ..tools.image_tool import generate_image
            path = await generate_image(
                args["prompt"],
                aspect_ratio=args.get("aspect_ratio", "1:1"),
                style_preset=args.get("style_preset", ""),
                negative_prompt=args.get("negative_prompt", ""),
                api_key=self._stability_api_key,
            )
            if not path.startswith("[ERROR]"):
                await self._send_file_to_user(recipient_id, path, channel)
                return f"[OK] Image generated and sent"
            return path

        else:
            return f"[ERROR] Unknown tool: {tool_name}"


# Global singleton
_registry: Optional[ToolRegistry] = None


def init_tools(**kwargs) -> ToolRegistry:
    global _registry
    _registry = ToolRegistry()
    _registry.configure(**kwargs)
    return _registry


def get_registry() -> ToolRegistry:
    if _registry is None:
        raise RuntimeError("Tools not initialized — call init_tools() first")
    return _registry
