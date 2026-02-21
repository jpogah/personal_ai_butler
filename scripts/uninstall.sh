#!/usr/bin/env bash
# Personal AI Butler — Uninstall Script
set -euo pipefail

BUTLER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.butler.agent.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Personal AI Butler — Uninstaller"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Unload daemon
if launchctl list | grep -q "com.butler.agent"; then
    echo "▶ Stopping and unloading daemon…"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    echo "  ✓ Daemon unloaded"
fi

# Remove plist
if [ -f "$PLIST_DST" ]; then
    rm "$PLIST_DST"
    echo "  ✓ Removed $PLIST_DST"
fi

echo
echo "The butler files at $BUTLER_HOME were NOT removed."
echo "To fully remove, run:  rm -rf $BUTLER_HOME"
echo
echo "Done."
