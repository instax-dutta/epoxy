#!/bin/sh
set -e

# Two ways to configure API keys:
#   1. Pterodactyl Startup tab (egg variables) — injected as OS env vars
#   2. Edit .env via Pterodactyl File Manager  — loaded by server.py at startup
# OS env vars always take precedence over .env file values.

# Bootstrap .env from .env.example only if both egg variables are empty
# AND no .env exists yet.
if [ ! -f "$HOME/.env" ]; then
    if [ -z "$GROQ_API_KEYS" ] && [ -z "$OLLAMA_API_KEYS" ]; then
        cp "$HOME/.env.example" "$HOME/.env"
        echo "============================================================"
        echo " Epoxy needs API keys."
        echo ""
        echo " Option A — Pterodactyl Startup tab (recommended):"
        echo "   Set GROQ_API_KEYS and OLLAMA_API_KEYS in the egg variables."
        echo ""
        echo " Option B — File Manager:"
        echo "   Edit /home/container/.env directly, then restart."
        echo "============================================================"
    else
        echo " Epoxy: using API keys from Pterodactyl egg variables."
    fi
fi

exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"
