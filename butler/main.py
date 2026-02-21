"""Personal AI Butler — main entry point."""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path
from typing import Optional

from .config import load_config, Config
from .database import init_db
from .utils.crypto import AuthGuard
from .utils.rate_limiter import RateLimiter
from .channels.base import InboundMessage, OutboundMessage, BaseChannel
from .channels.telegram_channel import TelegramChannel
from .channels.whatsapp_channel import WhatsAppChannel
from .permissions.classifier import RiskLevel
from .permissions.approval import ApprovalManager
from .ai.history import ConversationHistory
from .ai.engine import AIEngine
from .ai.tools import init_tools
from .tools.bash_tool import run_bash
from .tools.file_tool import file_read, file_write, file_list
from .tools.email_tool import EmailTool


def setup_logging(level: str, log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "butler.log"
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )


logger = logging.getLogger(__name__)


class Butler:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._db = None
        self._auth: Optional[AuthGuard] = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._channels: list[BaseChannel] = []
        self._engine: Optional[AIEngine] = None
        self._history: Optional[ConversationHistory] = None
        # Per-user ApprovalManager instances
        self._approvers: dict[str, ApprovalManager] = {}
        # Per-user pending reply channel (to send approval requests back)
        self._user_channels: dict[str, tuple[str, str]] = {}  # sender_id → (channel, recipient_id)
        # Dedup: set of recently seen message IDs
        self._seen_ids: set[str] = set()
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        cfg = self._cfg

        # Database
        self._db = await init_db(cfg.db_path)

        # Auth + rate limiting
        self._auth = AuthGuard(cfg.authorized_telegram_ids, cfg.authorized_whatsapp_phones)
        self._rate_limiter = RateLimiter(cfg.rate_limit_per_minute, cfg.rate_limit_burst)

        # Conversation history
        self._history = ConversationHistory(
            self._db,
            token_budget=cfg.history_token_budget,
            keep_recent=cfg.history_keep_recent,
        )

        # AI Engine
        api_key = cfg.anthropic_api_key or None
        self._engine = AIEngine(
            api_key=api_key,
            model=cfg.anthropic_model,
            max_tokens=cfg.anthropic_max_tokens,
            history=self._history,
        )

        # Email tool (optional)
        email_tool = None
        if cfg.email_enabled:
            email_tool = EmailTool(cfg.email_imap, cfg.email_smtp)

        # Browser config
        browser_cfg = {}
        if cfg.browser_enabled:
            browser_cfg = {
                "user_data_dir": cfg.browser_user_data_dir,
                "headless": cfg.browser_headless,
            }

        # Tool registry
        init_tools(
            bash_fn=run_bash,
            file_read_fn=file_read,
            file_write_fn=file_write,
            file_list_fn=file_list,
            file_send_fn=None,  # unused — file_send dispatched via send_file_to_user
            browser_cfg=browser_cfg,
            email_tool=email_tool,
            send_file_to_user=self._send_file_to_user,
            approver_factory=self._get_approver,
        )

        # Channels
        if cfg.telegram_enabled and cfg.telegram_token:
            tg = TelegramChannel(cfg.telegram_token, media_dir=cfg.media_dir)
            self._channels.append(tg)

        if cfg.whatsapp_enabled:
            wa = WhatsAppChannel(
                port=cfg.whatsapp_port,
                session_dir=cfg.whatsapp_session_dir,
                node_path=cfg.whatsapp_node_path,
                media_dir=cfg.media_dir,
            )
            self._channels.append(wa)

        if not self._channels:
            logger.error("No channels configured! Enable telegram or whatsapp in butler.yaml")
            return

        # Start channels
        for ch in self._channels:
            logger.info("Starting channel: %s", ch.channel_name)
            await ch.start(self._on_message)

        logger.info("Butler is running. Waiting for messages…")
        await self._shutdown_event.wait()

    def _get_approver(self, sender_id: str) -> ApprovalManager:
        """Get or create an ApprovalManager for this sender."""
        if sender_id not in self._approvers:
            async def _send_approval_msg(text: str):
                info = self._user_channels.get(sender_id)
                if not info:
                    return
                channel_name, recipient_id = info
                for ch in self._channels:
                    if ch.channel_name == channel_name:
                        try:
                            await ch.send(OutboundMessage(
                                channel=channel_name,
                                recipient_id=recipient_id,
                                text=text,
                            ))
                        except Exception as e:
                            logger.error("Failed to send approval msg: %s", e)
                        break

            self._approvers[sender_id] = ApprovalManager(
                send_fn=_send_approval_msg,
                timeout=self._cfg.approval_timeout,
            )
        return self._approvers[sender_id]

    async def _send_file_to_user(self, recipient_id: str, path: str, channel: str) -> None:
        for ch in self._channels:
            if ch.channel_name == channel:
                await ch.send(OutboundMessage(
                    channel=channel,
                    recipient_id=recipient_id,
                    text="",
                    media_path=path,
                ))
                return
        logger.warning("No channel found to send file: %s", channel)

    async def _on_message(self, msg: InboundMessage) -> None:
        """Handle an inbound message from any channel."""
        # Auth check
        if not self._auth.is_authorized(msg.channel, msg.sender_id):
            logger.warning("Unauthorized sender: %s on %s", msg.sender_id, msg.channel)
            return

        # Dedup
        if msg.message_id and msg.message_id in self._seen_ids:
            return
        if msg.message_id:
            self._seen_ids.add(msg.message_id)
            # Keep dedup set bounded
            if len(self._seen_ids) > 1000:
                self._seen_ids = set(list(self._seen_ids)[-500:])

        # Rate limit
        if not await self._rate_limiter.is_allowed(msg.sender_id):
            for ch in self._channels:
                if ch.channel_name == msg.channel:
                    await ch.send(OutboundMessage(
                        channel=msg.channel,
                        recipient_id=msg.sender_id,
                        text="⚠️ You're sending messages too fast. Please slow down.",
                    ))
            return

        # Track user's channel for approval messages
        self._user_channels[msg.sender_id] = (msg.channel, msg.sender_id)

        # Check if this is a reply to a pending approval
        approver = self._get_approver(msg.sender_id)
        if approver.has_pending() and msg.text:
            if approver.handle_reply(msg.text):
                return  # message was an approval reply, don't process as a new request

        # Spawn message processing as background task
        asyncio.create_task(
            self._process_message(msg),
            name=f"msg-{msg.channel}-{msg.sender_id}",
        )

    async def _process_message(self, msg: InboundMessage) -> None:
        """Process a message: show typing → run AI → reply."""
        # Find the right channel
        channel = next((ch for ch in self._channels if ch.channel_name == msg.channel), None)
        if not channel:
            return

        try:
            # Show typing indicator
            await channel.send_typing(msg.sender_id)

            # Get/create conversation
            conv_id = await self._history.get_or_create(msg.channel, msg.sender_id)

            # Run AI engine
            logger.info("[%s/%s] Processing: %s…", msg.channel, msg.sender_id, (msg.text or "")[:80])
            response = await self._engine.process(
                conv_id=conv_id,
                text=msg.text,
                media_path=msg.media_path,
                sender_id=msg.sender_id,
                channel=msg.channel,
                recipient_id=msg.sender_id,
            )

            # Send reply
            await channel.send(OutboundMessage(
                channel=msg.channel,
                recipient_id=msg.sender_id,
                text=response,
            ))

        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)
            try:
                await channel.send(OutboundMessage(
                    channel=msg.channel,
                    recipient_id=msg.sender_id,
                    text=f"❌ Error: {e}",
                ))
            except Exception:
                pass

    async def stop(self) -> None:
        logger.info("Shutting down Butler…")
        for ch in self._channels:
            try:
                await ch.stop()
            except Exception as e:
                logger.error("Error stopping channel %s: %s", ch.channel_name, e)

        # Close browser
        try:
            from .tools.browser_tool import close_browser
            await close_browser()
        except Exception:
            pass

        if self._db:
            await self._db.close()

        self._shutdown_event.set()
        logger.info("Butler stopped.")


async def _main():
    import sys
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/butler.yaml"

    cfg = load_config(config_path)
    setup_logging(cfg.log_level, cfg.log_dir)

    butler = Butler(cfg)

    loop = asyncio.get_running_loop()

    def _handle_signal():
        logger.info("Signal received, initiating shutdown…")
        asyncio.create_task(butler.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        await butler.start()
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
        raise


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
