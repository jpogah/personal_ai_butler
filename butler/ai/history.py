"""Conversation history with SQLite persistence and token-budget truncation."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

SESSION_WINDOW = 24 * 3600  # 24 hours: reuse existing conversation


class ConversationHistory:
    def __init__(
        self,
        db: aiosqlite.Connection,
        token_budget: int = 100_000,
        keep_recent: int = 10,
    ):
        self._db = db
        self._token_budget = token_budget
        self._keep_recent = keep_recent

    async def get_or_create(self, channel: str, sender_id: str) -> str:
        """Return active conversation ID (create if none active in last 24h)."""
        now = time.time()
        cutoff = now - SESSION_WINDOW

        async with self._db.execute(
            "SELECT id FROM conversations WHERE channel=? AND sender_id=? AND last_active>? "
            "ORDER BY last_active DESC LIMIT 1",
            (channel, sender_id, cutoff),
        ) as cur:
            row = await cur.fetchone()

        if row:
            conv_id = row["id"]
            await self._db.execute(
                "UPDATE conversations SET last_active=? WHERE id=?",
                (now, conv_id),
            )
        else:
            conv_id = str(uuid.uuid4())
            await self._db.execute(
                "INSERT INTO conversations (id, channel, sender_id, created_at, last_active) VALUES (?,?,?,?,?)",
                (conv_id, channel, sender_id, now, now),
            )

        await self._db.commit()
        return conv_id

    async def load(self, conv_id: str) -> list[dict]:
        """Load message history, applying token-budget truncation."""
        async with self._db.execute(
            "SELECT role, content, tokens FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conv_id,),
        ) as cur:
            rows = await cur.fetchall()

        messages = []
        for row in rows:
            content = json.loads(row["content"])
            messages.append({"role": row["role"], "content": content, "_tokens": row["tokens"]})

        # Apply token budget: always keep last keep_recent, then fill from oldest
        if not messages:
            return []

        recent = messages[-self._keep_recent:]
        older = messages[: -self._keep_recent]

        # Count recent tokens
        recent_tokens = sum(m["_tokens"] for m in recent)
        budget_remaining = self._token_budget - recent_tokens

        kept_older = []
        for msg in reversed(older):
            if budget_remaining <= 0:
                break
            kept_older.insert(0, msg)
            budget_remaining -= msg["_tokens"]

        result = kept_older + recent
        for m in result:
            m.pop("_tokens", None)

        return result

    async def append(self, conv_id: str, role: str, content: list | str, tokens: int = 0) -> None:
        """Append a message to conversation history."""
        if isinstance(content, str):
            content_json = json.dumps([{"type": "text", "text": content}])
        else:
            content_json = json.dumps(content)

        await self._db.execute(
            "INSERT INTO messages (conversation_id, role, content, tokens, created_at) VALUES (?,?,?,?,?)",
            (conv_id, role, content_json, tokens, time.time()),
        )
        await self._db.commit()
