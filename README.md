# Epoxy — Hermes Agent Free-Tier Proxy

Pool multiple free-tier **Groq** and **Ollama Cloud** API keys behind a single OpenAI-compatible endpoint with automatic key rotation, cooldown handling, and cross-provider fallback.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your comma-separated API keys
docker run -d --name epoxy -p 8080:8080 --env-file .env ghcr.io/instax-dutta/epoxy:latest
```

## Hermes Agent Setup

```yaml
custom_providers:
  free-pool:
    base_url: http://<your-server-ip>:8080
```

Then `/model groq-llama-3.1-8b-instant` or `/model ollama-deepseek-v3.1` in Hermes.

## Pterodactyl Deployment

1. Import `egg-epoxy.json` into your panel
2. Create server — Pterodactyl allocates the port via `SERVER_PORT`
3. Go to **File Manager**, open `/home/container/.env`, paste your keys
4. Restart the server (or just send a request — keys hot-reload on change)

Keys are managed exclusively via `.env`. No need to use the Startup tab.

## Rotation Strategies

Set via `GROQ_POOL_STRATEGY` / `OLLAMA_POOL_STRATEGY`:
- `round_robin` — cycle evenly (default)
- `fill_first` — drain one key before moving on
- `least_used` — pick least-used key
- `random` — random pick

## License

MIT
