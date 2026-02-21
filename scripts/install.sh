#!/usr/bin/env bash
# Personal AI Butler — Install Script
set -euo pipefail

BUTLER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.butler.agent.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Personal AI Butler — Installer"
echo "  Butler home: $BUTLER_HOME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Python virtual environment ────────────────────────────────────────────
echo
echo "▶ Step 1: Creating Python virtual environment…"
cd "$BUTLER_HOME"
python3 -m venv .venv
echo "  ✓ venv created at .venv/"

echo "▶ Step 1b: Installing Python dependencies…"
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "  ✓ Python packages installed"

# ── 2. Playwright Chromium ────────────────────────────────────────────────────
echo
echo "▶ Step 2: Installing Playwright Chromium browser…"
export PLAYWRIGHT_BROWSERS_PATH="$BUTLER_HOME/.playwright"
.venv/bin/playwright install chromium
echo "  ✓ Playwright Chromium installed to $PLAYWRIGHT_BROWSERS_PATH"

# ── 3. Node.js bridge ────────────────────────────────────────────────────────
echo
echo "▶ Step 3: Installing WhatsApp bridge Node.js dependencies…"
if ! command -v node &>/dev/null; then
    echo "  ⚠ Node.js not found in PATH. Install from https://nodejs.org/"
    echo "    Skipping bridge install (WhatsApp channel will be unavailable)"
else
    NODE_VERSION=$(node --version)
    echo "  Node.js $NODE_VERSION found"
    cd "$BUTLER_HOME/whatsapp_bridge"
    npm install --silent
    cd "$BUTLER_HOME"
    echo "  ✓ WhatsApp bridge installed"
fi

# ── 4. Data directories ───────────────────────────────────────────────────────
echo
echo "▶ Step 4: Creating data directories…"
mkdir -p \
    "$BUTLER_HOME/data/media" \
    "$BUTLER_HOME/data/sessions" \
    "$BUTLER_HOME/data/browser_profile" \
    "$BUTLER_HOME/logs"
echo "  ✓ Directories created"

# ── 5. Config ─────────────────────────────────────────────────────────────────
echo
echo "▶ Step 5: Setting up configuration…"
if [ ! -f "$BUTLER_HOME/config/butler.yaml" ]; then
    cp "$BUTLER_HOME/config/butler.yaml.example" "$BUTLER_HOME/config/butler.yaml"
    chmod 600 "$BUTLER_HOME/config/butler.yaml"
    echo "  ✓ Created config/butler.yaml (permissions: 600)"
    echo "  ⚠ IMPORTANT: Edit config/butler.yaml before starting!"
else
    echo "  ✓ config/butler.yaml already exists (not overwritten)"
fi

# ── 6. LaunchAgent plist ──────────────────────────────────────────────────────
echo
echo "▶ Step 6: Installing launchd daemon…"
PLIST_SRC="$BUTLER_HOME/launchd/$PLIST_NAME"
PLIST_DST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"
mkdir -p "$LAUNCH_AGENTS_DIR"

# Substitute placeholders
sed \
    -e "s|BUTLER_HOME|$BUTLER_HOME|g" \
    -e "s|HOME_DIR|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"

echo "  ✓ Plist installed to $PLIST_DST"
echo "  (Run 'scripts/start.sh' to load the daemon)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Installation complete!"
echo
echo "  Next steps:"
echo "  1. Edit config/butler.yaml (add your bot token, API key, etc.)"
echo "  2. Run:  scripts/start.sh     (start the daemon)"
echo "  3. Or:   scripts/run_dev.sh   (run in foreground for testing)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
