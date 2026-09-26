#!/bin/bash
set -e
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"
# Accept the documented shell-style .env, with or without export statements.
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi
exec /usr/bin/python3 -m main.desktop_launcher
