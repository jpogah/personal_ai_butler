"""WhatsApp channel adapter — spawns the Node bridge and connects via SSE."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import aiohttp

from .base import BaseChannel, InboundMessage, OutboundMessage, MessageHandler

logger = logging.getLogger(__name__)


class WhatsAppChannel(BaseChannel):
    """Manages the Node.js whatsapp-web.js bridge process and consumes its SSE stream."""

    def __init__(
        self,
        port: int = 8765,
        session_dir: str = "./data/sessions",
        node_path: str = "node",
        bridge_script: str = "./whatsapp_bridge/bridge.js",
        media_dir: str = "./data/media",
    ):
        self._port = port
        self._session_dir = session_dir
        self._node_path = node_path
        self._bridge_script = bridge_script
        self._media_dir = Path(media_dir)
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._process: Optional[asyncio.subprocess.Process] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._on_message: Optional[MessageHandler] = None
        self._base_url = f"http://127.0.0.1:{port}"

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    async def start(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        await self._start_bridge()
        await self._wait_for_bridge()
        self._session = aiohttp.ClientSession()
        self._sse_task = asyncio.create_task(self._consume_sse(), name="wa-sse")
        logger.info("WhatsApp channel started (bridge on port %d)", self._port)

    async def _start_bridge(self) -> None:
        script = Path(self._bridge_script).resolve()
        if not script.exists():
            raise FileNotFoundError(f"WhatsApp bridge script not found: {script}")

        env = os.environ.copy()
        self._process = await asyncio.create_subprocess_exec(
            self._node_path,
            str(script),
            "--port", str(self._port),
            "--session-dir", self._session_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        logger.info("WhatsApp bridge process started (PID %d)", self._process.pid)
        # Forward bridge stdout to our logger
        asyncio.create_task(self._forward_logs(), name="wa-logs")

    async def _forward_logs(self) -> None:
        """Forward bridge stdout directly to the terminal (preserves QR code rendering)."""
        if not self._process or not self._process.stdout:
            return
        import sys
        async for line in self._process.stdout:
            text = line.decode(errors="replace")
            # Print directly so QR ASCII art renders correctly in the terminal
            sys.stdout.write(text)
            sys.stdout.flush()

    async def _wait_for_bridge(self, timeout: float = 30.0) -> None:
        """Poll /health until bridge is up."""
        deadline = asyncio.get_event_loop().time() + timeout
        connector = aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as sess:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    async with sess.get(f"{self._base_url}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                        if r.status == 200:
                            logger.info("WhatsApp bridge is up")
                            return
                except Exception:
                    pass
                await asyncio.sleep(1)
        raise TimeoutError("WhatsApp bridge did not start within timeout")

    async def _consume_sse(self) -> None:
        """Long-lived SSE consumer loop."""
        retry_delay = 2.0
        while True:
            try:
                async with self._session.get(
                    f"{self._base_url}/events",
                    timeout=aiohttp.ClientTimeout(total=None, connect=10),
                    headers={"Accept": "text/event-stream"},
                ) as resp:
                    logger.info("SSE stream connected")
                    retry_delay = 2.0
                    async for line in resp.content:
                        text = line.decode().strip()
                        if text.startswith("data:"):
                            payload = text[5:].strip()
                            if payload:
                                await self._handle_event(json.loads(payload))
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("SSE connection lost: %s — retrying in %.0fs", e, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "qr":
            logger.info("WhatsApp QR generated — scan with your phone")
        elif etype == "ready":
            logger.info("WhatsApp is ready")
        elif etype == "disconnected":
            logger.warning("WhatsApp disconnected: %s", event.get("reason"))
        elif etype == "message":
            if not self._on_message:
                return
            inbound = InboundMessage(
                channel="whatsapp",
                sender_id=event.get("from", ""),
                sender_name=event.get("from_name", event.get("from", "")),
                text=event.get("body", ""),
                media_path=event.get("media_path"),
                message_id=event.get("id"),
            )
            try:
                await self._on_message(inbound)
            except Exception as e:
                logger.error("Error in on_message handler: %s", e, exc_info=True)

    async def send(self, message: OutboundMessage) -> None:
        if not self._session:
            raise RuntimeError("WhatsAppChannel not started")
        payload = {"to": message.recipient_id, "body": message.text or ""}
        if message.media_path:
            payload["media_path"] = message.media_path
        async with self._session.post(
            f"{self._base_url}/send",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Bridge send failed: {data.get('error')}")

    async def send_typing(self, recipient_id: str) -> None:
        if not self._session:
            return
        try:
            await self._session.post(
                f"{self._base_url}/send-typing",
                json={"to": recipient_id},
                timeout=aiohttp.ClientTimeout(total=5),
            )
        except Exception as e:
            logger.debug("send_typing failed: %s", e)

    async def stop(self) -> None:
        logger.info("Stopping WhatsApp channel…")
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
