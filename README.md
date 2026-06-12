# Epoxy — Hermes Agent Free-Tier Proxy

Pool multiple free-tier **Groq** and **Ollama Cloud** API keys behind a single OpenAI-compatible endpoint with automatic key rotation, cooldown handling, and cross-provider fallback.

When one key hits a rate limit, Epoxy rotates to the next — keeping Hermes Agent running without interruptions.

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your comma-separated API keys

# 2. Run with Docker
docker run -d --name epoxy -p 8080:8080 --env-file .env ghcr.io/<your-org>/epoxy:latest
```

## Hermes Agent Setup

Add to your Hermes `~/.hermes/config.yaml`:

```yaml
custom_providers:
  free-pool:
    base_url: http://<your-server-ip>:8080
```

Then in Hermes use `/model groq-llama-3.1-8b-instant` or `/model ollama-deepseek-v3.1`.

## Available Models

| Model Name | Backend |
|---|---|
| `groq-llama-3.1-8b-instant` | Groq |
| Any model with `llama-3`, `mixtral`, `gemma`, `whisper` | Groq |
| `ollama-deepseek-v3.1` | Ollama Cloud |
| Any model with `deepseek-v3`, `qwen3`, `kimi-`, `glm-`, `minimax-` | Ollama Cloud |

## Rotation Strategies

Set via `GROQ_POOL_STRATEGY` / `OLLAMA_POOL_STRATEGY` env vars:

| Strategy | Behavior |
|---|---|
| `round_robin` | Cycle evenly across all healthy keys (default) |
| `fill_first` | Drain first healthy key before moving on |
| `least_used` | Pick key with fewest requests |
| `random` | Random selection among healthy keys |

## Deploy to Pterodactyl

Import `egg-epoxy.json` into your Pterodactyl panel as a new egg. Set `GROQ_API_KEYS` and `OLLAMA_API_KEYS` in the server's Startup tab.

## Build from Source

```bash
docker build -t epoxy .
```

## License

MIT
