#!/usr/bin/env bash
# Run butler in the foreground (development/testing mode)
set -euo pipefail

BUTLER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BUTLER_HOME"

if [ ! -f ".venv/bin/python" ]; then
    echo "venv not found. Run scripts/install.sh first."
    exit 1
fi

if [ ! -f "config/butler.yaml" ]; then
    echo "config/butler.yaml not found. Copy from config/butler.yaml.example and fill in values."
    exit 1
fi

export PLAYWRIGHT_BROWSERS_PATH="$BUTLER_HOME/.playwright"
exec .venv/bin/python -m butler.main config/butler.yaml
