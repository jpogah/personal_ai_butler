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
