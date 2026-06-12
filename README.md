# Epoxy — Hermes Agent Free-Tier Proxy

Pool free-tier API keys from **Groq**, **Ollama Cloud**, and **Mistral** behind a single OpenAI-compatible endpoint with automatic key rotation, cooldown handling, and cross-provider fallback.

## Quick Start

```bash
cp .env.example .env
# Add your keys (GROQ_API_KEYS, OLLAMA_API_KEYS, MISTRAL_API_KEYS)
docker run -d --name epoxy -p 8080:8080 --env-file .env ghcr.io/instax-dutta/epoxy:latest
```

## Hermes Agent Setup

```yaml
custom_providers:
  free-pool:
    base_url: http://<your-server-ip>:8080
```

Then `/model groq-llama-3.1-8b-instant`, `/model ollama-deepseek-v4-flash:cloud`, or `/model mistral-large-latest`.

## Supported Models

| Model name | Provider |
|---|---|
| `groq-llama-3.1-8b-instant` | Groq |
| `ollama-deepseek-v4-flash:cloud` | Ollama Cloud |
| `ollama-minimax-m3:cloud` | Ollama Cloud (MiniMax M3) |
| `mistral-large-latest` | Mistral |
| Any model with `llama-3`, `mixtral`, `gemma` | Groq |
| Any model with `deepseek-v3/4`, `qwen3`, `kimi-`, `minimax-` | Ollama Cloud |
| Any model with `mistral-`, `codestral-` | Mistral |

## Pterodactyl Deployment

1. Import `egg-epoxy.json` into your panel
2. Create server — port allocated via `SERVER_PORT`
3. **File Manager** → edit `/home/container/.env` → paste keys
4. Restart (or just send a request — keys hot-reload on change)

## Rotation Strategies

Set via `GROQ_POOL_STRATEGY`, `OLLAMA_POOL_STRATEGY`, `MISTRAL_POOL_STRATEGY`:
- `round_robin` (default), `fill_first`, `least_used`, `random`

## License

MIT
