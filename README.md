<p align="center">
  <h1 align="center">Epoxy</h1>
  <p align="center"><em>Free-tier LLM proxy for Hermes Agent</em></p>
  <p align="center">
    Pools multiple Groq, Ollama Cloud &amp; Mistral API keys behind a single OpenAI-compatible endpoint.<br>
    Auto key rotation · 429/402/401 cooldowns · Hot-reload · Pterodactyl &amp; Docker
  </p>
  <p align="center">
    <a href="#quickstart"><strong>Quickstart »</strong></a>
    ·
    <a href="#deployment"><strong>Deployment</strong></a>
    ·
    <a href="#api"><strong>API Reference</strong></a>
  </p>
</p>

<br>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python" alt="Python version">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/github/actions/workflow/status/instax-dutta/epoxy/docker-publish.yml?logo=github&label=build" alt="Build">
  <img src="https://img.shields.io/github/v/release/instax-dutta/epoxy?logo=github" alt="Release">
  <img src="https://img.shields.io/badge/architecture-amd64%20%7C%20arm64-lightgrey" alt="Architecture">
</p>

---

## Features

- **Multi-provider pooling** — Combine keys from Groq, Ollama Cloud, and Mistral into one endpoint.
- **Automatic key rotation** — Round-robin, fill-first, least-used, or random strategies per provider.
- **Intelligent cooldowns** — Rate-limited (429 → 1h), exhausted (402 → 24h), or auth failures (401 → immediate removal).
- **Cross-provider fallback** — If the routed provider has no healthy keys, Epoxy falls through to any configured provider.
- **Model routing** — Keyword-based model → provider dispatch. No config needed; just pick a model name.
- **Hot-reload** — Edit `.env` and the next request picks up changes. No restart required.
- **Pterodactyl native** — Import the egg, set keys via File Manager, done.

---

## Quickstart

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env: add your GROQ_API_KEYS, OLLAMA_API_KEYS, MISTRAL_API_KEYS

# 2. Run with Docker
docker run -d \
  --name epoxy \
  -p 8080:8080 \
  --env-file .env \
  ghcr.io/instax-dutta/epoxy:latest

# 3. Use with any OpenAI-compatible client
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "groq-llama-3.1-8b-instant",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

---

## Hermes Agent Setup

```yaml
# config.yml
custom_providers:
  free-pool:
    base_url: http://<your-server-ip>:8080
```

Then use any supported model by name:

```
/model groq-llama-3.1-8b-instant
/model ollama-deepseek-v4-flash:cloud
/model mistral-large-latest
```

---

## Supported Models

### Groq
| Model |
|---|
| `groq-llama-3.1-8b-instant` |
| `groq-llama-3.3-70b-versatile` |
| `groq-gemma2-9b-it` |
| `groq-deepseek-r1-distill-llama-70b` |
| `groq-compound-beta` |

### Ollama Cloud
| Model |
|---|
| `ollama-deepseek-v4-flash:cloud` |
| `ollama-minimax-m3:cloud` |
| `ollama-minimax-m2.7:cloud` |
| `ollama-glm-5.1:cloud` |
| `ollama-nemotron-3-super:cloud` |

### Mistral
| Model |
|---|
| `mistral-large-latest` |
| `mistral-small-latest` |
| `open-mistral-nemo` |

### Automatic keyword routing

Any model name containing these keywords routes to the corresponding provider:

| Provider | Keywords |
|---|---|
| **Groq** | `llama-3`, `llama3`, `mixtral`, `gemma`, `whisper`, `deepseek-r1-distill` |
| **Ollama Cloud** | `deepseek-v3`, `deepseek-v4`, `qwen3`, `kimi-`, `minimax-`, `glm-`, `cogito-`, `nemotron-`, `gpt-oss`, `:`, `cloud` |
| **Mistral** | `mistral-`, `codestral-`, `open-mistral`, `open-mixtral`, `open-codestral` |

If no keyword matches, the first provider with keys is used.

---

## Configuration

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `GROQ_API_KEYS` | Comma-separated Groq API keys | — |
| `OLLAMA_API_KEYS` | Comma-separated Ollama Cloud keys | — |
| `MISTRAL_API_KEYS` | Comma-separated Mistral API keys | — |
| `GROQ_POOL_STRATEGY` | Key selection strategy for Groq | `round_robin` |
| `OLLAMA_POOL_STRATEGY` | Key selection strategy for Ollama | `round_robin` |
| `MISTRAL_POOL_STRATEGY` | Key selection strategy for Mistral | `round_robin` |
| `SERVER_PORT` / `PORT` | Server port | `8080` |

### Pool strategies

| Strategy | Behavior |
|---|---|
| `round_robin` | Distributes evenly across all healthy keys |
| `fill_first` | Uses the first healthy key until it fails |
| `least_used` | Picks the key with fewest requests |
| `random` | Picks a random healthy key |

### Cooldown behavior

| HTTP status | Duration | Trigger |
|---|---|---|
| 429 | 1 hour | Rate-limited — key is skipped, then retried once before cooling down |
| 402 | 24 hours | Quota exhausted |
| 401 | Permanent | Auth error — key is permanently removed from rotation |

### Key hot-reload

Epoxy monitors `.env` file modification time. On each request, if `.env` has changed, pools are reloaded transparently. No restart needed.

To force a reload without changing the file:

```bash
curl -X POST http://localhost:8080/reload
```

---

## Deployment

### Docker

```bash
docker run -d \
  --name epoxy \
  -p 8080:8080 \
  --env-file .env \
  --restart unless-stopped \
  ghcr.io/instax-dutta/epoxy:latest
```

Multi-arch images are available for `linux/amd64` and `linux/arm64`.

### Pterodactyl

1. Download [`egg-epoxy.json`](./egg-epoxy.json) and import it manually into your panel.
2. Create a server — the port is allocated via `SERVER_PORT` (Pterodactyl allocation).
3. Open **File Manager**, edit `/home/container/.env`, and paste your API keys. **Do not** set keys in Startup variables.
4. Start the server. Keys hot-reload on file change, so future edits take effect immediately.

---

## API

### `GET /health`

Returns pool status for each configured provider.

```json
{
  "status": "ok",
  "providers": {
    "groq": {
      "total": 3,
      "healthy": 2,
      "strategy": "round_robin",
      "keys": [
        {"label": "...abc123", "status": "ok", "request_count": 42},
        {"label": "...def456", "status": "rate_limited", "request_count": 7}
      ]
    }
  }
}
```

### `GET /v1/models`

Lists all available models across all configured providers.

### `GET /v1/capabilities`

Returns platform capabilities.

### `POST /v1/chat/completions`

OpenAI-compatible chat completions endpoint. Supports streaming (`stream: true`).

Request and response bodies follow the [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat) format.

### `POST /reload`

Force-reload API keys from `.env` without restarting.

---

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│             │     │               Epoxy                      │
│  Hermes     │     │  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  Agent      │─────│  │   Groq   │  │  Ollama  │  │ Mistral│  │
│  / Client   │     │  │   Pool   │  │   Pool   │  │  Pool  │  │
│             │     │  ├──────────┤  ├──────────┤  ├────────┤  │
│             │     │  │ round    │  │ round    │  │ round  │  │
│             │     │  │ _robin   │  │ _robin   │  │ _robin │  │
│             │     │  │          │  │          │  │        │  │
│             │     │  │ Key 1 ✓  │  │ Key 1 ✓  │  │ Key 1 ✓│  │
│             │     │  │ Key 2 ✗  │  │ Key 2 ✓  │  │        │  │
│             │     │  │ Key 3 ✓  │  │          │  │        │  │
│             │     │  └──────────┘  └──────────┘  └────────┘  │
│             │     │         \            |          /         │
│             │     │          \           |         /          │
│             │     │     ┌──────────────────────────┐         │
│             │     │     │   Model Router:           │         │
│             │     │     │   keyword → provider      │         │
│             │     │     └──────────────────────────┘         │
│             │     │              ↕ HTTP POST                  │
│             │     │      /v1/chat/completions                 │
└─────────────┘     └──────────────────────────────────────────┘
```

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python server.py

# Run tests
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](./LICENSE) (or the repository license file).
