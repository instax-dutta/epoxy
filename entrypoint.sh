#!/bin/sh
set -e

# ─────────────────────────────────────────────
# Epoxy - API key configuration
#
# API keys are stored in /home/container/.env.
# Edit this file through Pterodactyl's File Manager,
# then either:
#   - Restart the container, or
#   - Make a request (keys reload on next request)
#     or POST to /reload for an immediate reload.
#
# Pterodactyl will map its allocated port
# (SERVER_PORT) to the container. Epoxy reads
# SERVER_PORT, then PORT, then defaults to 8080.
# ─────────────────────────────────────────────

if [ ! -f "$HOME/.env" ]; then
    cp "$HOME/.env.example" "$HOME/.env"
    echo "============================================================"
    echo " Epoxy needs API keys."
    echo ""
    echo " Edit /home/container/.env via Pterodactyl File Manager,"
    echo " then restart the container (or send a request to reload)."
    echo "============================================================"
fi

PORT="${SERVER_PORT:-${PORT:-8080}}"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT"
