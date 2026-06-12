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

### Groq (5 models)
| Model name |
|---|
| `groq-llama-3.1-8b-instant` |
| `groq-llama-3.3-70b-versatile` |
| `groq-gemma2-9b-it` |
| `groq-deepseek-r1-distill-llama-70b` |
| `groq-compound-beta` |

### Ollama Cloud (5 models)
| Model name |
|---|
| `ollama-deepseek-v4-flash:cloud` |
| `ollama-minimax-m3:cloud` |
| `ollama-minimax-m2.7:cloud` |
| `ollama-glm-5.1:cloud` |
| `ollama-nemotron-3-super:cloud` |

### Mistral (3 models)
| Model name |
|---|
| `mistral-large-latest` |
| `mistral-small-latest` |
| `open-mistral-nemo` |

### Keyword-based routing
| Keyword | Provider |
|---|---|
| `llama-3`, `llama3`, `mixtral`, `gemma`, `whisper`, `deepseek-r1-distill` | Groq |
| `deepseek-v3`, `deepseek-v4`, `qwen3`, `kimi-`, `minimax-`, `glm-`, `cogito-`, `nemotron-`, `gpt-oss` | Ollama Cloud |
| `mistral-`, `codestral-`, `open-mistral`, `open-mixtral`, `open-codestral` | Mistral |
| contains `:` or `cloud` in name | Ollama Cloud |

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
