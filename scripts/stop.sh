#!/usr/bin/env bash
# Stop the butler daemon (without uninstalling)
launchctl stop com.butler.agent 2>/dev/null && echo "✓ Butler stopped." || echo "Butler was not running."
