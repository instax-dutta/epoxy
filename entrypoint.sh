#!/bin/sh
set -e

# Epoxy — API key configuration
#
# Keys are stored in /home/container/.env.
# Edit through Pterodactyl's File Manager.
# Reloads automatically on change (no restart needed).
#
# Supported providers:
#   GROQ_API_KEYS   — Groq (free-tier)
#   OLLAMA_API_KEYS — Ollama Cloud
#   MISTRAL_API_KEYS — Mistral API

if [ ! -f "$HOME/.env" ]; then
    cp "$HOME/.env.example" "$HOME/.env"
    echo "============================================================"
    echo " Epoxy needs API keys."
    echo ""
    echo " Edit /home/container/.env via Pterodactyl File Manager."
    echo " Set one or more of:"
    echo "   GROQ_API_KEYS"
    echo "   OLLAMA_API_KEYS"
    echo "   MISTRAL_API_KEYS"
    echo " Then restart or send any request (auto-reloads)."
    echo "============================================================"
fi

PORT="${SERVER_PORT:-${PORT:-8080}}"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT"
