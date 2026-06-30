<p align="center">
  <h1 align="center">Epoxy</h1>
  <p align="center"><em>Universal Free-Tier LLM Key Rotation Proxy</em></p>
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

## Integration Examples

Epoxy exposes a standard OpenAI-compatible API. Point any client at it by changing the base URL.

> **Note:** The port depends on your deployment — check the server logs for the actual URL (e.g., `http://0.0.0.0:9013`). Replace `8080` in the examples below with your port.

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<host>:8080/v1",
    api_key="any-string",  # auth is not enforced
)
response = client.chat.completions.create(
    model="groq-llama-3.1-8b-instant",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Node.js (openai SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://<host>:8080/v1',
  apiKey: 'any-string',
});
const response = await client.chat.completions.create({
  model: 'groq-llama-3.1-8b-instant',
  messages: [{ role: 'user', content: 'Hello!' }],
});
```

### Open WebUI

In **Settings → Connections**, set:
- **OpenAI API URL**: `http://<host>:8080/v1`
- **API Key**: any string (e.g., `epoxy`)

### AnythingLLM

In **Settings → LLM Preference → OpenAI**, set:
- **Base URL**: `http://<host>:8080/v1`
- **API Key**: any string

### LM Studio

In **Server → OpenAI Compatible Server**, set:
- **Base URL**: `http://<host>:8080/v1`
- **API Key**: any string

*Any client that accepts a custom OpenAI base URL works.*

---

### OpenCode

Configure a custom provider in `~/.config/opencode/opencode.json`:

```json
{
  "provider": {
    "epoxy": {
      "name": "Epoxy",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://<host>:8080/v1"
      },
      "models": {
        "groq-llama-3.1-8b-instant": { "name": "Groq Llama 3.1 8B" },
        "groq-llama-3.3-70b-versatile": { "name": "Groq Llama 3.3 70B" },
        "groq-deepseek-r1-distill-llama-70b": { "name": "Groq DeepSeek R1 70B" },
        "ollama-deepseek-v4-flash:cloud": { "name": "Ollama DeepSeek V4 Flash" },
        "ollama-qwen3.5:cloud": { "name": "Ollama Qwen 3.5" },
        "ollama-gpt-oss:120b-cloud": { "name": "Ollama GPT-OSS 120B" }
      }
    }
  }
}
```

Then add your API key via `/connect` (any string works) and select an Epoxy model from the model picker.

### Kilo Code

In **Kilo Code Settings → Providers → Add Provider**, select **OpenAI Compatible** and fill in:

- **Base URL**: `http://<host>:8080/v1`
- **API Key**: any string

The model list will auto-fetch. Select any Epoxy model (e.g., `groq-llama-3.1-8b-instant`) as your default.

Or via `kilo.jsonc`:

```json
{
  "provider": {
    "epoxy": {
      "name": "Epoxy",
      "baseURL": "http://<host>:8080/v1",
      "apiKey": "any-string",
      "models": {
        "groq-llama-3.1-8b-instant": { "name": "Groq Llama 3.1 8B", "id": "groq-llama-3.1-8b-instant" },
        "groq-llama-3.3-70b-versatile": { "name": "Groq Llama 3.3 70B", "id": "groq-llama-3.3-70b-versatile" },
        "ollama-deepseek-v4-flash:cloud": { "name": "Ollama DeepSeek V4 Flash", "id": "ollama-deepseek-v4-flash:cloud" }
      }
    }
  }
}
```

### Claude Code

Claude Code uses the Anthropic Messages API, not OpenAI Chat Completions. To use Epoxy models, run a translation proxy alongside it:

```bash
# Example using claude-code-proxy
git clone https://github.com/shirayner/cc-proxy
# Configure OPENAI_API_KEY and OPENAI_BASE_URL=http://<host>:8080/v1 in .env
python start_proxy.py

# Then point Claude Code at the proxy
ANTHROPIC_BASE_URL=http://localhost:8082 ANTHROPIC_API_KEY=any-value claude
```

### Cline

In **Cline Settings → API Provider**, select **OpenAI Compatible**:

- **Base URL**: `http://<host>:8080/v1`
- **API Key**: any string
- **Model ID**: pick any Epoxy model (e.g., `groq-llama-3.1-8b-instant`)

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

## Supported Models

### Groq — Fast & Reasoning
| Category | Model |
|---|---|
| 🧠 Reasoning | `groq-llama-3.3-70b-versatile` |
| ⚡ Fast | `groq-llama-3.1-8b-instant` |
| ⚡ Fast | `groq-mixtral-8x7b-32768` |
| ⚡ Fast | `groq-gemma2-9b-it` |
| 🧠 Reasoning | `groq-deepseek-r1-distill-llama-70b` |
| ⚡ Fast | `groq-gemma-7b-it` |
| 🛡️ Guard | `groq-llama-guard-3-8b` |
| 🧠 Reasoning | `groq-llama3-70b-8192` |
| ⚡ Fast | `groq-llama3-8b-8192` |
| 🎤 Audio | `groq-whisper-large-v3` |

### Ollama Cloud — Reasoning, Code & Creative
| Category | Model |
|---|---|
| 🧠 Reasoning | `ollama-glm-5.2:cloud` |
| ⚡ Fast | `ollama-nemotron-3-super:cloud` |
| ✨ Creative | `ollama-minimax-m3:cloud` |
| 🧠 Reasoning | `ollama-glm-5.1:cloud` |
| ✨ Creative | `ollama-kimi-k2.6:cloud` |
| ✨ Creative | `ollama-minimax-m2.7:cloud` |
| ⚡ Fast | `ollama-deepseek-v4-flash:cloud` |
| 🧠 Reasoning | `ollama-gpt-oss:120b-cloud` |
| ⚡ Fast | `ollama-gpt-oss:20b-cloud` |
| ⚡ Fast | `ollama-gemma4:cloud` |
| 🧠 Reasoning | `ollama-nemotron-3-ultra:cloud` |
| 💻 Code | `ollama-kimi-k2.7-code:cloud` |
| 💻 Code | `ollama-qwen3.5:cloud` |
| 🧠 Reasoning | `ollama-glm-5:cloud` |

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
| **Groq** | `llama-3`, `llama3`, `mixtral`, `gemma`, `gemma2`, `whisper`, `deepseek-r1-distill`, `compound` |
| **Ollama Cloud** | `gpt-oss`, `kimi-`, `minimax-`, `glm-`, `qwen3`, `qwen3.5`, `cogito-`, `nemotron-`, `deepseek-v4`, `deepseek-v3`, `gemma4`, `:`, `cloud` |
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
┌──────────────────────┐     ┌──────────────────────────────────────────┐
│                      │     │               Epoxy                      │
│  Any OpenAI-         │     │  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  compatible          │─────│  │   Groq   │  │  Ollama  │  │ Mistral│  │
│  Client              │     │  │   Pool   │  │   Pool   │  │  Pool  │  │
│                      │     │  ├──────────┤  ├──────────┤  ├────────┤  │
│                      │     │  │ round    │  │ round    │  │ round  │  │
│                      │     │  │ _robin   │  │ _robin   │  │ _robin │  │
│                      │     │  │          │  │          │  │        │  │
│                      │     │  │ Key 1 ✓  │  │ Key 1 ✓  │  │ Key 1 ✓│  │
│                      │     │  │ Key 2 ✗  │  │ Key 2 ✓  │  │        │  │
│                      │     │  │ Key 3 ✓  │  │          │  │        │  │
│                      │     │  └──────────┘  └──────────┘  └────────┘  │
│                      │     │         \            |          /         │
│                      │     │          \           |         /          │
│                      │     │     ┌──────────────────────────┐         │
│                      │     │     │   Model Router:           │         │
│                      │     │     │   keyword → provider      │         │
│                      │     │     └──────────────────────────┘         │
│                      │     │              ↕ HTTP POST                  │
│                      │     │      /v1/chat/completions                 │
└──────────────────────┘     └──────────────────────────────────────────┘
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
