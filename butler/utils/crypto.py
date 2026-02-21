"""AuthGuard: sender allowlist checker."""
import logging
from typing import Set

logger = logging.getLogger(__name__)


class AuthGuard:
    """Checks that incoming messages are from authorized senders."""

    def __init__(self, telegram_ids: list[int | str], whatsapp_phones: list[str]):
        self._telegram: Set[str] = {str(uid) for uid in telegram_ids}
        # Normalize E.164: keep only digits and leading +
        self._whatsapp: Set[str] = {self._normalize_phone(p) for p in whatsapp_phones}
        logger.info(
            "AuthGuard initialized: %d Telegram IDs, %d WhatsApp phones",
            len(self._telegram),
            len(self._whatsapp),
        )

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        phone = phone.strip()
        if not phone.startswith("+"):
            phone = "+" + phone
        return phone

    def is_authorized_telegram(self, user_id: int | str) -> bool:
        return str(user_id) in self._telegram

    def is_authorized_whatsapp(self, phone: str) -> bool:
        return self._normalize_phone(phone) in self._whatsapp

    def is_authorized(self, channel: str, sender_id: str) -> bool:
        if channel == "telegram":
            return self.is_authorized_telegram(sender_id)
        elif channel == "whatsapp":
            return self.is_authorized_whatsapp(sender_id)
        return False
