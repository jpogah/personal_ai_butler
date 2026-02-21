"""Telegram channel adapter using python-telegram-bot v21+."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from telegram import Update, Bot
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)

from .base import BaseChannel, InboundMessage, OutboundMessage, MessageHandler as MsgHandler

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """Polls Telegram for messages, calls on_message callback."""

    def __init__(self, bot_token: str, media_dir: str = "./data/media"):
        self._token = bot_token
        self._media_dir = Path(media_dir)
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self._app: Optional[Application] = None
        self._on_message: Optional[MsgHandler] = None

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def start(self, on_message: MsgHandler) -> None:
        self._on_message = on_message
        self._app = Application.builder().token(self._token).build()

        # Register handler for text + media messages (not commands)
        self._app.add_handler(
            MessageHandler(
                filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.AUDIO | filters.VOICE,
                self._handle_update,
            )
        )

        logger.info("Starting Telegram polling…")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def _handle_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not self._on_message:
            return

        msg = update.message
        user = msg.from_user
        sender_id = str(user.id) if user else "unknown"
        sender_name = user.full_name if user else "Unknown"

        # Download media if present
        media_path: Optional[str] = None
        try:
            if msg.photo:
                file_obj = await context.bot.get_file(msg.photo[-1].file_id)
                ext = "jpg"
            elif msg.document:
                file_obj = await context.bot.get_file(msg.document.file_id)
                ext = msg.document.file_name.split(".")[-1] if msg.document.file_name else "bin"
            elif msg.audio:
                file_obj = await context.bot.get_file(msg.audio.file_id)
                ext = "mp3"
            elif msg.voice:
                file_obj = await context.bot.get_file(msg.voice.file_id)
                ext = "ogg"
            else:
                file_obj = None
                ext = ""

            if file_obj:
                dest = self._media_dir / f"tg_{msg.message_id}.{ext}"
                await file_obj.download_to_drive(str(dest))
                media_path = str(dest)
        except Exception as e:
            logger.warning("Failed to download media: %s", e)

        inbound = InboundMessage(
            channel="telegram",
            sender_id=sender_id,
            sender_name=sender_name,
            text=msg.text or msg.caption or "",
            media_path=media_path,
            message_id=str(msg.message_id),
        )

        try:
            await self._on_message(inbound)
        except Exception as e:
            logger.error("Error in on_message handler: %s", e, exc_info=True)

    async def send(self, message: OutboundMessage) -> None:
        if not self._app:
            raise RuntimeError("TelegramChannel not started")

        bot: Bot = self._app.bot
        chat_id = int(message.recipient_id)

        # Split long messages (Telegram limit: 4096 chars)
        text = message.text or ""
        if message.media_path:
            path = Path(message.media_path)
            if path.exists():
                with open(path, "rb") as f:
                    await bot.send_document(chat_id=chat_id, document=f, caption=text[:1024] or None)
                return

        # Chunk text if needed
        chunks = [text[i:i+4096] for i in range(0, max(len(text), 1), 4096)]
        for chunk in chunks:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)

    async def send_typing(self, recipient_id: str) -> None:
        if not self._app:
            return
        try:
            await self._app.bot.send_chat_action(chat_id=int(recipient_id), action="typing")
        except Exception as e:
            logger.debug("send_typing failed: %s", e)

    async def stop(self) -> None:
        if self._app:
            logger.info("Stopping Telegram channel…")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None
