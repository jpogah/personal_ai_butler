#!/usr/bin/env bash
# Restart the butler daemon (picks up code changes)
launchctl kickstart -k gui/$(id -u)/com.butler.agent && echo "✓ Butler restarted."
