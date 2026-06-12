#!/bin/sh
set -e

# If no .env exists, bootstrap from .env.example
if [ ! -f "$HOME/.env" ] && [ -f "$HOME/.env.example" ]; then
    cp "$HOME/.env.example" "$HOME/.env"
    echo " Created $HOME/.env from .env.example — edit it with your API keys."
fi

exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"
