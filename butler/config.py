"""Configuration loader: YAML file + optional macOS Keychain fallback."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_KEYCHAIN_MARKER = "keychain:"


def _keychain_get(service: str, account: str) -> str | None:
    """Fetch a secret from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug("Keychain lookup failed: %s", e)
    return None


def _resolve_secrets(obj: Any) -> Any:
    """Recursively resolve keychain: references in config values."""
    if isinstance(obj, str):
        if obj.startswith(_KEYCHAIN_MARKER):
            spec = obj[len(_KEYCHAIN_MARKER):].strip()
            parts = spec.split(":", 1)
            service = parts[0].strip()
            account = parts[1].strip() if len(parts) > 1 else service
            secret = _keychain_get(service, account)
            if secret:
                logger.debug("Resolved Keychain secret for service=%s account=%s", service, account)
                return secret
            else:
                logger.warning("Keychain secret not found: service=%s account=%s", service, account)
                return ""
        return obj
    elif isinstance(obj, dict):
        return {k: _resolve_secrets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_secrets(v) for v in obj]
    return obj


class Config:
    """Loaded, validated configuration."""

    def __init__(self, raw: dict):
        self._raw = raw

    def get(self, *keys, default=None):
        """Navigate nested keys: cfg.get('email', 'imap', 'host')"""
        obj = self._raw
        for key in keys:
            if not isinstance(obj, dict):
                return default
            obj = obj.get(key, None)
            if obj is None:
                return default
        return obj

    # ── Convenience accessors ─────────────────────────────────────────────

    @property
    def telegram_token(self) -> str:
        return self.get("telegram", "bot_token", default="")

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.get("telegram", "enabled", default=True))

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.get("whatsapp", "enabled", default=False))

    @property
    def whatsapp_port(self) -> int:
        return int(self.get("whatsapp", "bridge", "port", default=8765))

    @property
    def whatsapp_session_dir(self) -> str:
        return self.get("whatsapp", "bridge", "session_dir", default="./data/sessions")

    @property
    def whatsapp_node_path(self) -> str:
        return self.get("whatsapp", "bridge", "node_path", default="node")

    @property
    def anthropic_api_key(self) -> str:
        return self.get("anthropic", "api_key", default="")

    @property
    def anthropic_model(self) -> str:
        return self.get("anthropic", "model", default="claude-sonnet-4-6")

    @property
    def anthropic_max_tokens(self) -> int:
        return int(self.get("anthropic", "max_tokens", default=4096))

    @property
    def history_token_budget(self) -> int:
        return int(self.get("anthropic", "history_token_budget", default=100_000))

    @property
    def history_keep_recent(self) -> int:
        return int(self.get("anthropic", "history_keep_recent", default=10))

    @property
    def authorized_telegram_ids(self) -> list:
        return self.get("security", "authorized_senders", "telegram", default=[])

    @property
    def authorized_whatsapp_phones(self) -> list:
        return self.get("security", "authorized_senders", "whatsapp", default=[])

    @property
    def rate_limit_per_minute(self) -> int:
        return int(self.get("security", "rate_limit", "messages_per_minute", default=10))

    @property
    def rate_limit_burst(self) -> int:
        return int(self.get("security", "rate_limit", "burst", default=3))

    @property
    def approval_timeout(self) -> float:
        return float(self.get("permissions", "approval_timeout", default=60))

    @property
    def db_path(self) -> str:
        return self.get("paths", "db_path", default="./data/butler.db")

    @property
    def media_dir(self) -> str:
        return self.get("paths", "media_dir", default="./data/media")

    @property
    def log_dir(self) -> str:
        return self.get("paths", "log_dir", default="./logs")

    @property
    def email_enabled(self) -> bool:
        return bool(self.get("email", "enabled", default=False))

    @property
    def email_imap(self) -> dict:
        return self.get("email", "imap", default={})

    @property
    def email_smtp(self) -> dict:
        return self.get("email", "smtp", default={})

    @property
    def browser_enabled(self) -> bool:
        return bool(self.get("browser", "enabled", default=True))

    @property
    def browser_user_data_dir(self) -> str:
        return self.get("browser", "user_data_dir", default="./data/browser_profile")

    @property
    def browser_headless(self) -> bool:
        return bool(self.get("browser", "headless", default=True))

    @property
    def log_level(self) -> str:
        return self.get("logging", "level", default="INFO").upper()


def load_config(path: str = "config/butler.yaml") -> Config:
    """Load and return configuration from YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Copy config/butler.yaml.example to config/butler.yaml and fill in your values."
        )

    with open(p, "r") as f:
        raw = yaml.safe_load(f) or {}

    raw = _resolve_secrets(raw)
    logger.info("Config loaded from %s", path)
    return Config(raw)
