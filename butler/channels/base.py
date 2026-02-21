"""Base types and abstract channel interface."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional


@dataclass
class InboundMessage:
    """Normalized message arriving from any channel."""
    channel: str          # 'telegram' | 'whatsapp'
    sender_id: str        # channel-specific user/phone identifier
    sender_name: str      # human-readable display name
    text: str
    media_path: Optional[str] = None   # local path to downloaded media file
    message_id: Optional[str] = None   # original message ID for dedup


@dataclass
class OutboundMessage:
    """Message to send back through a channel."""
    channel: str
    recipient_id: str
    text: str
    media_path: Optional[str] = None   # path to file to attach
    reply_to_id: Optional[str] = None


# Type alias for the callback signature
MessageHandler = Callable[[InboundMessage], Awaitable[None]]


class BaseChannel(abc.ABC):
    """Abstract base for messaging channel adapters."""

    @property
    @abc.abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier string."""
        ...

    @abc.abstractmethod
    async def start(self, on_message: MessageHandler) -> None:
        """Start listening; call on_message for each inbound message."""
        ...

    @abc.abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """Send a message to the recipient."""
        ...

    @abc.abstractmethod
    async def send_typing(self, recipient_id: str) -> None:
        """Send typing indicator if supported."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""
        ...
