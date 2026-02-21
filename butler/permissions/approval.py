"""Approval manager: request human approval for risky actions via chat."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Callable, Awaitable, Optional

from .classifier import RiskLevel

logger = logging.getLogger(__name__)

# Type: async function that sends a text message to the user
SendFn = Callable[[str], Awaitable[None]]


class ApprovalManager:
    """
    Manages pending approval requests for a single user/channel.

    Usage:
        approved = await mgr.request_approval("bash", {"command": "rm foo"}, RiskLevel.HIGH)

    When the user replies with "yes"/"no", call:
        handled = mgr.handle_reply("yes")
    """

    def __init__(
        self,
        send_fn: SendFn,
        timeout: float = 60.0,
        auto_approve_below: RiskLevel = RiskLevel.LOW,
    ):
        self._send = send_fn
        self._timeout = timeout
        self._auto_approve_below = auto_approve_below
        # request_id → asyncio.Future[bool]
        self._pending: dict[str, asyncio.Future] = {}
        self._current_id: Optional[str] = None
        # "yes all" mode: auto-approve everything until reset
        self._yes_all = False

    async def request_approval(
        self, tool_name: str, args: dict, risk: RiskLevel
    ) -> bool:
        """
        Returns True if action is approved, False if denied/timed out.
        Auto-approves if risk <= auto_approve_below.
        """
        if risk <= self._auto_approve_below or self._yes_all:
            return True

        request_id = str(uuid.uuid4())[:8].upper()
        self._current_id = request_id

        # Format approval message
        args_preview = json.dumps(args, ensure_ascii=False)
        if len(args_preview) > 300:
            args_preview = args_preview[:297] + "..."

        msg = (
            f"⚠️ *Permission Required* [{request_id}]\n"
            f"Tool: `{tool_name}`\n"
            f"Risk: {risk.label()}\n"
            f"Args: `{args_preview}`\n\n"
            f"Reply *yes* to approve, *no* to deny, *yes all* to approve all until restart.\n"
            f"_(Timeout in {int(self._timeout)}s)_"
        )

        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        await self._send(msg)

        try:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval request %s timed out", request_id)
            self._pending.pop(request_id, None)
            if self._current_id == request_id:
                self._current_id = None
            await self._send(f"⏰ Request [{request_id}] timed out — action *denied* automatically.")
            return False
        finally:
            self._pending.pop(request_id, None)

        return result

    def handle_reply(self, text: str) -> bool:
        """
        Parse a user reply text and resolve the pending Future.
        Returns True if a pending request was resolved.
        """
        normalized = text.strip().lower()

        # Check for "yes all"
        if normalized in ("yes all", "yesall", "y all"):
            self._yes_all = True
            # Approve any pending
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_result(True)
            self._pending.clear()
            self._current_id = None
            return True

        is_yes = normalized in ("yes", "y", "approve", "ok", "yep", "sure")
        is_no = normalized in ("no", "n", "deny", "cancel", "nope", "stop")

        if not (is_yes or is_no):
            return False

        if not self._current_id or self._current_id not in self._pending:
            return False

        fut = self._pending.get(self._current_id)
        if fut and not fut.done():
            fut.set_result(is_yes)
            self._pending.pop(self._current_id, None)
            self._current_id = None
            return True

        return False

    def has_pending(self) -> bool:
        return bool(self._pending)

    def reset_yes_all(self) -> None:
        self._yes_all = False
