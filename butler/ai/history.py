"""Conversation history with perpetual sessions, summarization, and user memory."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional, Callable, Awaitable

import aiosqlite

logger = logging.getLogger(__name__)

# Chunk size: summarize this many messages at a time when truncating
SUMMARY_CHUNK_SIZE = 20

# Type for the summarization callback
SummarizeFn = Callable[[list[dict]], Awaitable[str]]


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
        """Return the single perpetual conversation ID for this user (creates on first use)."""
        async with self._db.execute(
            "SELECT id FROM conversations WHERE channel=? AND sender_id=? "
            "ORDER BY last_active DESC LIMIT 1",
            (channel, sender_id),
        ) as cur:
            row = await cur.fetchone()

        now = time.time()
        if row:
            conv_id = row["id"]
            await self._db.execute(
                "UPDATE conversations SET last_active=? WHERE id=?", (now, conv_id)
            )
        else:
            conv_id = str(uuid.uuid4())
            await self._db.execute(
                "INSERT INTO conversations (id, channel, sender_id, created_at, last_active) VALUES (?,?,?,?,?)",
                (conv_id, channel, sender_id, now, now),
            )

        await self._db.commit()
        return conv_id

    async def load(
        self,
        conv_id: str,
        sender_id: str = "",
        channel: str = "",
        summarize_fn: Optional[SummarizeFn] = None,
    ) -> list[dict]:
        """
        Load message history for the API/prompt, with:
        - User memory injected at the top
        - Past summaries injected after memory
        - Recent messages filling the remaining token budget
        - Auto-summarization of messages being evicted (if summarize_fn provided)
        """
        # ── 1. Load user memory ────────────────────────────────────────────
        memory_block = await self._load_user_memory(sender_id, channel) if sender_id else ""

        # ── 2. Load existing summaries ────────────────────────────────────
        async with self._db.execute(
            "SELECT content FROM summaries WHERE conversation_id=? ORDER BY created_at",
            (conv_id,),
        ) as cur:
            summary_rows = await cur.fetchall()
        summaries_text = "\n\n".join(r["content"] for r in summary_rows)

        # ── 3. Load all messages ──────────────────────────────────────────
        async with self._db.execute(
            "SELECT id, role, content, tokens FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conv_id,),
        ) as cur:
            rows = await cur.fetchall()

        all_messages = []
        for row in rows:
            content = json.loads(row["content"])
            all_messages.append({
                "id": row["id"],
                "role": row["role"],
                "content": content,
                "_tokens": row["tokens"],
            })

        if not all_messages:
            return _build_context(memory_block, summaries_text, [])

        # ── 4. Apply token budget ─────────────────────────────────────────
        recent = all_messages[-self._keep_recent:]
        older = all_messages[: -self._keep_recent]

        recent_tokens = sum(m["_tokens"] for m in recent)
        budget_remaining = self._token_budget - recent_tokens

        kept_older = []
        evicted = []
        for msg in reversed(older):
            if budget_remaining > 0:
                kept_older.insert(0, msg)
                budget_remaining -= msg["_tokens"]
            else:
                evicted.insert(0, msg)

        # ── 5. Summarize evicted messages ─────────────────────────────────
        if evicted and summarize_fn:
            await self._summarize_and_store(conv_id, evicted, summarize_fn)
            # Reload summaries after new ones were added
            async with self._db.execute(
                "SELECT content FROM summaries WHERE conversation_id=? ORDER BY created_at",
                (conv_id,),
            ) as cur:
                summary_rows = await cur.fetchall()
            summaries_text = "\n\n".join(r["content"] for r in summary_rows)

        # ── 6. Strip internal ID field before returning ───────────────────
        kept = kept_older + recent
        for m in kept:
            m.pop("id", None)
            m.pop("_tokens", None)

        return _build_context(memory_block, summaries_text, kept)

    async def _summarize_and_store(
        self,
        conv_id: str,
        messages: list[dict],
        summarize_fn: SummarizeFn,
    ) -> None:
        """Summarize evicted messages in chunks and store in DB."""
        # Check which message IDs are already covered by existing summaries
        async with self._db.execute(
            "SELECT first_msg_id, last_msg_id FROM summaries WHERE conversation_id=?",
            (conv_id,),
        ) as cur:
            covered = {(r["first_msg_id"], r["last_msg_id"]) for r in await cur.fetchall()}

        # Process in chunks
        for i in range(0, len(messages), SUMMARY_CHUNK_SIZE):
            chunk = messages[i: i + SUMMARY_CHUNK_SIZE]
            first_id = chunk[0]["id"]
            last_id = chunk[-1]["id"]

            # Skip if already summarized
            if any(first_id >= f and last_id <= l for f, l in covered):
                continue

            logger.info("Summarizing %d evicted messages (ids %d–%d)", len(chunk), first_id, last_id)
            try:
                summary = await summarize_fn(chunk)
                await self._db.execute(
                    "INSERT INTO summaries (conversation_id, content, first_msg_id, last_msg_id, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (conv_id, summary, first_id, last_id, time.time()),
                )
                await self._db.commit()
            except Exception as e:
                logger.warning("Failed to summarize chunk: %s", e)

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

    # ── User memory ────────────────────────────────────────────────────────

    async def save_memory(self, sender_id: str, channel: str, key: str, value: str) -> None:
        """Store a memorable fact about the user."""
        await self._db.execute(
            "INSERT OR REPLACE INTO user_memory (sender_id, channel, key, value, updated_at) VALUES (?,?,?,?,?)",
            (sender_id, channel, key.strip().lower(), value.strip(), time.time()),
        )
        await self._db.commit()
        logger.info("Saved memory [%s/%s] %s = %s", channel, sender_id, key, value[:80])

    async def forget_memory(self, sender_id: str, channel: str, key: str) -> bool:
        """Remove a remembered fact. Returns True if it existed."""
        async with self._db.execute(
            "SELECT id FROM user_memory WHERE sender_id=? AND channel=? AND key=?",
            (sender_id, channel, key.strip().lower()),
        ) as cur:
            row = await cur.fetchone()
        if row:
            await self._db.execute(
                "DELETE FROM user_memory WHERE sender_id=? AND channel=? AND key=?",
                (sender_id, channel, key.strip().lower()),
            )
            await self._db.commit()
            return True
        return False

    async def list_memories(self, sender_id: str, channel: str) -> dict[str, str]:
        """Return all remembered facts for a user."""
        async with self._db.execute(
            "SELECT key, value FROM user_memory WHERE sender_id=? AND channel=? ORDER BY updated_at DESC",
            (sender_id, channel),
        ) as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def _load_user_memory(self, sender_id: str, channel: str) -> str:
        """Return a formatted memory block, or empty string if none."""
        memories = await self.list_memories(sender_id, channel)
        if not memories:
            return ""
        lines = [f"• {k}: {v}" for k, v in memories.items()]
        return "Things I remember about you:\n" + "\n".join(lines)


def _build_context(memory_block: str, summaries_text: str, messages: list[dict]) -> list[dict]:
    """
    Prepend memory + summaries as the first exchange in the message list.
    Uses a user→assistant ping-pong so the API format stays valid.
    """
    context_parts = []
    if memory_block:
        context_parts.append(memory_block)
    if summaries_text:
        context_parts.append("Summary of our past conversations:\n" + summaries_text)

    if not context_parts:
        return messages

    context_text = "\n\n".join(context_parts)
    context_messages = [
        {"role": "user", "content": [{"type": "text", "text": context_text}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Got it — I have that context in mind."}]},
    ]
    return context_messages + messages
