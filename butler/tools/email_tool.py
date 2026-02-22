"""Email tool: IMAP read + SMTP send."""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import smtplib
import textwrap
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Optional

from ..permissions.classifier import RiskLevel
from ..permissions.approval import ApprovalManager

logger = logging.getLogger(__name__)


def _imap_list_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    count: int = 10,
    folder: str = "INBOX",
) -> str:
    """Synchronous IMAP fetch (runs in executor)."""
    try:
        with imaplib.IMAP4_SSL(host, port) as conn:
            conn.login(username, password)
            conn.select(folder, readonly=True)
            _, data = conn.search(None, "ALL")
            ids = data[0].split()
            recent = ids[-count:] if len(ids) >= count else ids
            recent = list(reversed(recent))  # newest first

            lines = []
            for num in recent:
                _, msg_data = conn.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                # imaplib can return mixed tuples; find the bytes part
                header_bytes = None
                for part in msg_data:
                    if isinstance(part, tuple):
                        header_bytes = part[1]
                        break
                if not header_bytes or not isinstance(header_bytes, bytes):
                    continue
                msg = email.message_from_bytes(header_bytes)
                subject = msg.get("Subject", "(no subject)")
                from_ = msg.get("From", "?")
                date = msg.get("Date", "?")
                num_str = num.decode() if isinstance(num, bytes) else str(num)
                lines.append(f"[{num_str}] From: {from_}\n    Subject: {subject}\n    Date: {date}")

            return "\n\n".join(lines) if lines else "(no messages)"
    except Exception as e:
        return f"[ERROR] IMAP list failed: {e}"


def _imap_read_email(
    host: str,
    port: int,
    username: str,
    password: str,
    message_id: str,
    folder: str = "INBOX",
) -> str:
    """Synchronous IMAP read (runs in executor)."""
    try:
        with imaplib.IMAP4_SSL(host, port) as conn:
            conn.login(username, password)
            conn.select(folder, readonly=True)
            _, msg_data = conn.fetch(message_id.encode(), "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            from_ = msg.get("From", "?")
            to = msg.get("To", "?")
            subject = msg.get("Subject", "?")
            date = msg.get("Date", "?")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="replace")

            body = body.strip()
            if len(body) > 4000:
                body = body[:4000] + "\n…[truncated]"

            return (
                f"From: {from_}\nTo: {to}\nSubject: {subject}\nDate: {date}\n\n{body}"
            )
    except Exception as e:
        return f"[ERROR] IMAP read failed: {e}"


def _smtp_send(
    host: str,
    port: int,
    username: str,
    password: str,
    from_address: str,
    to: str,
    subject: str,
    body: str,
) -> str:
    """Synchronous SMTP send (runs in executor)."""
    try:
        msg = EmailMessage()
        msg["From"] = from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

        logger.info("Email sent to %s: %s", to, subject)
        return f"[OK] Email sent to {to}"
    except Exception as e:
        return f"[ERROR] SMTP send failed: {e}"


class EmailTool:
    def __init__(self, imap_cfg: dict, smtp_cfg: dict):
        self._imap = imap_cfg
        self._smtp = smtp_cfg

    async def list_emails(self, count: int = 10, folder: str = "INBOX") -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _imap_list_emails,
            self._imap["host"],
            self._imap["port"],
            self._imap["username"],
            self._imap["password"],
            count,
            folder,
        )

    async def read_email(self, message_id: str, folder: str = "INBOX") -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _imap_read_email,
            self._imap["host"],
            self._imap["port"],
            self._imap["username"],
            self._imap["password"],
            message_id,
            folder,
        )

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        approver: Optional[ApprovalManager] = None,
    ) -> str:
        if approver:
            approved = await approver.request_approval(
                "email_send",
                {"to": to, "subject": subject, "body_preview": body[:200]},
                RiskLevel.HIGH,
            )
            if not approved:
                return f"[DENIED] Sending email to {to!r} was denied."

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _smtp_send,
            self._smtp["host"],
            self._smtp["port"],
            self._smtp["username"],
            self._smtp["password"],
            self._smtp.get("from_address", self._smtp["username"]),
            to,
            subject,
            body,
        )
