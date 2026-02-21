#!/usr/bin/env bash
# Load the butler LaunchAgent daemon
set -euo pipefail

PLIST_DST="$HOME/Library/LaunchAgents/com.butler.agent.plist"

if [ ! -f "$PLIST_DST" ]; then
    echo "Plist not found. Run scripts/install.sh first."
    exit 1
fi

if launchctl list | grep -q "com.butler.agent"; then
    echo "Butler is already running. Use 'launchctl stop com.butler.agent' to stop it first."
    exit 1
fi

launchctl load "$PLIST_DST"
echo "✓ Butler daemon started."
echo "  Logs: tail -f logs/butler.log"
echo "  Status: launchctl list | grep butler"
