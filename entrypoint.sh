#!/bin/sh
set -e

# Copy fresh app files from image — overwrites stale volume copies
cp /app/server.py "$HOME/server.py"
cp /app/entrypoint.sh "$HOME/entrypoint.sh"
chmod +x "$HOME/entrypoint.sh"
cp /app/.env.example "$HOME/.env.example"

# Ensure deps are installed (fast no-op if already present)
pip install --no-cache-dir -r /app/requirements.txt > /dev/null 2>&1 || true

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
