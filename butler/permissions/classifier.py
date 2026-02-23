"""Risk classification for tool calls."""
from __future__ import annotations

import re
from enum import IntEnum


class RiskLevel(IntEnum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def label(self) -> str:
        return {
            RiskLevel.SAFE: "✅ SAFE",
            RiskLevel.LOW: "🟢 LOW",
            RiskLevel.MEDIUM: "🟡 MEDIUM",
            RiskLevel.HIGH: "🔴 HIGH",
            RiskLevel.CRITICAL: "🚨 CRITICAL",
        }[self]


# Bash command patterns → risk level (patterns checked in order, first match wins)
_BASH_RULES: list[tuple[re.Pattern, RiskLevel]] = [
    # CRITICAL — always block / always ask
    (re.compile(r"rm\s+-[rf]+\s*/\b|rm\s+--no-preserve-root"), RiskLevel.CRITICAL),
    (re.compile(r":\(\)\s*\{.*\|.*\&"), RiskLevel.CRITICAL),          # fork bomb
    (re.compile(r"dd\s+if=/dev/(random|zero|urandom)"), RiskLevel.CRITICAL),
    (re.compile(r"\bmkfs\b|\bformat\b"), RiskLevel.CRITICAL),
    (re.compile(r">\s*/dev/sd[a-z]"), RiskLevel.CRITICAL),

    # HIGH
    (re.compile(r"\brm\s+(-[rf]+\s+)?\S"), RiskLevel.HIGH),           # any rm
    (re.compile(r"\bsudo\b|\bdoas\b"), RiskLevel.HIGH),
    (re.compile(r"\bchmod\s+[0-7]*[0-7][0-7][0-7]\b"), RiskLevel.HIGH),
    (re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b"), RiskLevel.HIGH),        # curl | bash
    (re.compile(r"\bkill\b|\bkillall\b"), RiskLevel.HIGH),
    (re.compile(r"\blaunchctl\s+(load|unload|bootstrap|bootout)\b"), RiskLevel.HIGH),
    (re.compile(r"\bsystemctl\s+(start|stop|restart|enable|disable)\b"), RiskLevel.HIGH),
    (re.compile(r"\bpkill\b"), RiskLevel.HIGH),
    (re.compile(r"\bcrontab\b"), RiskLevel.HIGH),
    (re.compile(r"\bnetwork\b.*\bset\b|\bifconfig\b.*\bdown\b"), RiskLevel.HIGH),

    # MEDIUM
    (re.compile(r"\bmv\b"), RiskLevel.MEDIUM),
    (re.compile(r"\bcp\s+.*\s+/"), RiskLevel.MEDIUM),
    (re.compile(r"\bssh\b|\brsync\b|\bscp\b"), RiskLevel.MEDIUM),
    (re.compile(r"\bbrewup\b|\bbrew\s+(install|uninstall|upgrade)\b"), RiskLevel.MEDIUM),
    (re.compile(r"\bnpm\s+(install|uninstall)\b|\bpip\s+(install|uninstall)\b"), RiskLevel.MEDIUM),
    (re.compile(r"\bgit\s+(push|reset|rebase|force)\b"), RiskLevel.MEDIUM),
    (re.compile(r"\bopen\s+-a\b"), RiskLevel.MEDIUM),

    # LOW
    (re.compile(r"\bmkdir\b|\btouch\b|\becho\b|\bcat\b"), RiskLevel.LOW),
    (re.compile(r"\bgrep\b|\bfind\b|\bls\b|\bpwd\b|\bwhoami\b|\bdate\b"), RiskLevel.LOW),
    (re.compile(r"\bpython\b|\bnode\b|\bruby\b|\bperl\b"), RiskLevel.LOW),

    # SAFE (default for simple read ops)
    (re.compile(r"^(ls|pwd|whoami|date|echo|cat|head|tail|grep|wc)\b"), RiskLevel.SAFE),
]

# Base risk for each tool (before arg-specific analysis)
TOOL_BASE_RISKS: dict[str, RiskLevel] = {
    "bash": RiskLevel.MEDIUM,
    "file_read": RiskLevel.SAFE,
    "file_write": RiskLevel.MEDIUM,
    "file_list": RiskLevel.SAFE,
    "file_send": RiskLevel.LOW,
    "browser_navigate": RiskLevel.LOW,
    "browser_click": RiskLevel.LOW,
    "browser_type": RiskLevel.LOW,
    "browser_get_text": RiskLevel.SAFE,
    "browser_screenshot": RiskLevel.SAFE,
    "screenshot": RiskLevel.SAFE,
    "email_list": RiskLevel.LOW,
    "email_read": RiskLevel.LOW,
    "email_send": RiskLevel.HIGH,
    # LinkedIn
    "linkedin_get_feed": RiskLevel.SAFE,
    "linkedin_get_notifications": RiskLevel.SAFE,
    "linkedin_get_messages": RiskLevel.SAFE,
    "linkedin_get_pages": RiskLevel.SAFE,
    "linkedin_connect": RiskLevel.MEDIUM,
    "linkedin_comment": RiskLevel.MEDIUM,
    "linkedin_send_message": RiskLevel.HIGH,
    "linkedin_post": RiskLevel.HIGH,
    "linkedin_page_post": RiskLevel.HIGH,
    # Instagram
    "instagram_get_feed":          RiskLevel.SAFE,
    "instagram_get_notifications": RiskLevel.SAFE,
    "instagram_get_messages":      RiskLevel.SAFE,
    "instagram_follow":            RiskLevel.MEDIUM,
    "instagram_like":              RiskLevel.LOW,
    "instagram_comment":           RiskLevel.MEDIUM,
    "instagram_send_message":      RiskLevel.HIGH,
    "instagram_post":              RiskLevel.HIGH,
}


def classify_bash(command: str) -> RiskLevel:
    """Classify a bash command string into a RiskLevel."""
    for pattern, level in _BASH_RULES:
        if pattern.search(command):
            return level
    # Default: medium (unknown commands might be risky)
    return RiskLevel.MEDIUM


def classify_tool(tool_name: str, args: dict) -> RiskLevel:
    """Return risk level for a tool call."""
    base = TOOL_BASE_RISKS.get(tool_name, RiskLevel.MEDIUM)

    if tool_name == "bash":
        cmd = args.get("command", "")
        bash_risk = classify_bash(cmd)
        return max(base, bash_risk)

    if tool_name == "file_write":
        path = args.get("path", "")
        # Writing to system paths is higher risk
        if any(path.startswith(p) for p in ["/etc/", "/usr/", "/bin/", "/sbin/", "/System/"]):
            return RiskLevel.CRITICAL

    return base
