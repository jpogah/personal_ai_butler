# Personal AI Butler

A personal AI assistant that runs as a macOS background service, bridging **Telegram** and **WhatsApp** to Claude AI. Message it from your phone to control your Mac — run commands, manage files, automate the browser, monitor email, and more.

Works with your **Claude Max subscription** (no API key required) or the Anthropic API.

---

## Features

- **Telegram & WhatsApp** — message the butler from any device
- **Shell commands** — run bash, check system status, manage processes
- **File system** — read, write, list, and send files back to your chat
- **Browser automation** — navigate, click, type, and screenshot via Playwright
- **Email** — list and read emails via IMAP, send via SMTP
- **Screenshots** — capture browser page or full desktop and receive in chat
- **Risk-based permissions** — low-risk actions auto-approved, medium/high ask you first
- **Conversation memory** — 24h session windows stored in SQLite
- **macOS daemon** — auto-starts on login via LaunchAgent, restarts on crash

---

## Architecture

```
[Telegram Bot]  [WhatsApp Bridge (Node.js)]
       └──────────────┬──────────────────┘
              Message Router (Auth + Rate Limit)
                       │
              ApprovalManager (risk-based gating)
                       │
              AI Engine (Claude Max CLI / Claude API)
                       │
         ┌─────────────┼─────────────┐
       Bash          Browser        Email
      (shell)     (Playwright)   (IMAP/SMTP)
                       │
                  File System
```

---

## Requirements

- macOS (tested on macOS 14+)
- Python 3.11+
- Node.js 18+
- [Claude Code](https://claude.ai/download) CLI (for Max subscription mode) **or** Anthropic API key

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/jpogah/personal_ai_butler.git
cd personal_ai_butler
scripts/install.sh
```

### 2. Configure

```bash
cp config/butler.yaml.example config/butler.yaml
chmod 600 config/butler.yaml
nano config/butler.yaml
```

Key fields to fill in:

| Field | How to get it |
|-------|--------------|
| `telegram.bot_token` | Message [@BotFather](https://t.me/BotFather) → `/newbot` |
| `security.authorized_senders.telegram` | Message [@userinfobot](https://t.me/userinfobot) → `/start` |
| `anthropic.api_key` | [console.anthropic.com](https://console.anthropic.com) — leave empty for Claude Max CLI |
| `email.imap/smtp` | Gmail + [App Password](https://myaccount.google.com/apppasswords) |

### 3. Run

```bash
# Foreground (development/testing)
scripts/run_dev.sh

# Background daemon (auto-starts on login)
scripts/start.sh
```

---

## WhatsApp Setup

WhatsApp requires a dedicated phone number for the bridge (it runs as a WhatsApp Web session):

1. Get a second number (e.g. [Google Voice](https://voice.google.com) — free US number)
2. Register WhatsApp with that number
3. Enable WhatsApp in `butler.yaml` and disable Telegram
4. Run `scripts/run_dev.sh` — a QR code appears in the terminal
5. Scan with the second WhatsApp account (Settings → Linked Devices)
6. Message the butler's number from your personal phone

---

## Usage Examples

Send these to your butler via Telegram or WhatsApp:

```
What files are on my Desktop?
Run: df -h
Open google.com and take a screenshot
List my last 5 emails
Write a Python script to rename all .jpg files in ~/Downloads
What's my Mac's current CPU usage?
```

For risky actions (deleting files, sending email, etc.) the butler will ask for confirmation:

```
Butler: ⚠️ Permission Required [A3F2]
        Tool: bash
        Risk: 🔴 HIGH
        Args: {"command": "rm ~/Downloads/old_backup.zip"}
        Reply yes to approve, no to deny.

You: yes
Butler: ✅ Done.
```

---

## Risk Levels

| Level | Examples | Action |
|-------|----------|--------|
| SAFE | `ls`, `pwd`, `date` | Auto-approved |
| LOW | `mkdir`, `cat`, `grep` | Auto-approved |
| MEDIUM | `mv`, `brew install`, `git push` | Asks permission |
| HIGH | `rm`, `sudo`, `kill`, `send email` | Asks permission |
| CRITICAL | `rm -rf /`, fork bombs | Always blocked |

---

## Project Structure

```
personal_ai_butler/
├── butler/
│   ├── main.py              # Entry point + orchestrator
│   ├── config.py            # YAML loader (supports macOS Keychain)
│   ├── database.py          # SQLite schema
│   ├── channels/            # Telegram + WhatsApp adapters
│   ├── ai/                  # Claude engine + tool definitions + history
│   ├── tools/               # bash, file, browser, email, screenshot
│   ├── permissions/         # Risk classifier + approval flow
│   └── utils/               # Auth guard + rate limiter
├── whatsapp_bridge/         # Node.js Express + whatsapp-web.js
├── config/
│   └── butler.yaml.example  # Config template
├── launchd/                 # macOS LaunchAgent plist
├── scripts/                 # install, start, stop, run_dev, uninstall
└── requirements.txt
```

---

## Configuration Reference

See [`config/butler.yaml.example`](config/butler.yaml.example) for all options with inline documentation.

### macOS Keychain support

Store secrets in Keychain instead of plain text:

```yaml
anthropic:
  api_key: "keychain:claude-butler:api_key"
```

Then add the secret: `security add-generic-password -s claude-butler -a api_key -w YOUR_KEY`

---

## Daemon Management

```bash
scripts/start.sh      # load LaunchAgent (auto-start on login)
scripts/stop.sh       # stop without uninstalling
scripts/restart.sh    # restart and pick up code changes
scripts/uninstall.sh  # remove daemon
launchctl list | grep butler  # check status
tail -f logs/butler.log       # view logs
```

## Development Workflow

After editing any source file, apply changes with:

```bash
scripts/restart.sh
```

For active development with live terminal output:

```bash
scripts/stop.sh       # stop the daemon
scripts/run_dev.sh    # run in foreground (Ctrl+C to stop)
scripts/start.sh      # reload daemon when done
```

After pulling updates from GitHub:

```bash
git pull
scripts/restart.sh
```

If `requirements.txt` changed:

```bash
git pull
.venv/bin/pip install -r requirements.txt
scripts/restart.sh
```

---

## License

MIT — see [LICENSE](LICENSE)

---

## Contributing

PRs welcome. Key areas for contribution:
- Additional tool integrations (calendar, reminders, notes)
- Telegram inline keyboard for approval buttons
- Web UI dashboard for conversation history
- Support for other messaging platforms
