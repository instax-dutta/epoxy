# Epoxy Renovation Plan: Agent-First Lightweight Proxy

**Vision:** Epoxy becomes the go-to lightweight free-tier LLM pooling proxy optimized for AI coding agents (Claude Code, OpenCode, Kilo Code, Cline, Continue, etc.) — deployed in seconds on Windows, Raspberry Pi, Pterodactyl, or Docker.

**Core Differentiator:** "Tool-call efficient models only. Zero bloat. Every agent framework works. Your spare PC becomes a $19/month equivalent."

---

## Phase 1: Agent Framework Integration (Week 1-2)

### 1.1 Claude Code Native Support
**Goal:** Claude Code users open Epoxy dashboard, paste their unified API key, and code with 5 free models instantly.

**Tasks:**
- [ ] Document Anthropic Messages API mapping in README
  - Show exact curl example for `/v1/messages`
  - Explain: FreeLLMAPI translates OpenAI → Anthropic; Epoxy should too (if models support it)
- [ ] Add Anthropic model routing to server.py
  ```python
  # New route: POST /v1/messages (Anthropic compat)
  @app.post("/v1/messages")
  async def anthropic_chat_completions(request: Request):
      # Translate Anthropic format → OpenAI format → route → translate back
      body = await request.json()
      openai_body = anthropic_to_openai(body)
      # ... route and call providers ...
      return openai_to_anthropic(result)
  ```
- [ ] Create `docs/CLAUDE_CODE_SETUP.md`
  ```bash
  # One-liner setup docs
  export ANTHROPIC_BASE_URL=http://localhost:8080
  export ANTHROPIC_AUTH_TOKEN=any-string
  claude
  ```

**PR Acceptance Criteria:**
- Claude Code connects to Epoxy and completes at least one multi-turn coding task
- Test against a real project (e.g., "write a CLI to-do app")
- Screenshot in PR description

---

### 1.2 OpenCode Integration
**Goal:** OpenCode users run `/connect` and select Epoxy from provider list.

**Tasks:**
- [ ] Update README Integration section with working OpenCode config
  ```json
  {
    "provider": {
      "epoxy": {
        "name": "Epoxy (Free Tier Pooling)",
        "npm": "@ai-sdk/openai-compatible",
        "options": {
          "baseURL": "http://localhost:8080/v1"
        },
        "models": {
          "groq-llama-3.3-70b-versatile": { "name": "Groq Llama 3.3 70B (Reasoning)" },
          "groq-llama-3.1-8b-instant": { "name": "Groq Llama 3.1 8B (Fast)" }
        }
      }
    }
  }
  ```
- [ ] Document: "Models update automatically when you add new keys"
- [ ] Add OpenCode to "Works With" section of root README

**PR Acceptance Criteria:**
- OpenCode `/connect` loads Epoxy provider
- Model auto-discovery works
- Completion succeeds with Epoxy endpoint

---

### 1.3 Kilo Code Integration
**Goal:** Kilo Code users see Epoxy in provider dropdown, add keys, code.

**Tasks:**
- [ ] Add to README: Kilo Code config section (copy from existing, verify URL format)
- [ ] Ensure `/v1/models` response matches Kilo's expected schema
- [ ] Create `docs/KILO_CODE_SETUP.md`

**PR Acceptance Criteria:**
- Kilo Code connects, lists models, completes a task

---

### 1.4 Cline Integration
**Goal:** Cline (Claude extension) points at Epoxy without friction.

**Tasks:**
- [ ] Update docs: Cline → Settings → API Provider → OpenAI Compatible
- [ ] Verify Cline's request format works with `/v1/chat/completions`
- [ ] Add Cline screenshot to README

**PR Acceptance Criteria:**
- Cline connects to Epoxy
- Task completes (e.g., "create a React component")

---

### 1.5 Continue Integration
**Goal:** Continue dev-mode users route autocomplete + chat through Epoxy.

**Tasks:**
- [ ] Ensure `/v1/completions` endpoint handles legacy prompt/suffix (VS Code ghost-text)
- [ ] Document Continue config in README
  ```yaml
  models:
    - name: Epoxy Chat
      provider: openai
      model: groq-llama-3.1-8b-instant
      apiBase: http://localhost:8080/v1
      apiKey: any-string
    - name: Epoxy Autocomplete
      provider: openai
      model: groq-llama-3.1-8b-instant
      apiBase: http://localhost:8080/v1
      apiKey: any-string
      useLegacyCompletionsEndpoint: true
      roles:
        - autocomplete
  ```
- [ ] Add Continue to "Works With" list

**PR Acceptance Criteria:**
- Continue chat works
- Ghost-text autocomplete works (or document why it doesn't for specific models)

---

### 1.6 Codex + MimoCode (Research)
**Goal:** Document compatibility or add support if feasible.

**Tasks:**
- [ ] Research Codex agent API surface → does it use OpenAI-compat?
- [ ] Research MimoCode → same question
- [ ] Add documentation section "Researched Agents" with findings
- [ ] If compatible: add setup docs; if not, explain why and recommend workaround

**PR Acceptance Criteria:**
- Research document completed
- Findings in `docs/AGENT_COMPATIBILITY.md`

---

## Phase 2: Tool-Call Efficiency & Model Curation (Week 2-3)

### 2.1 Tool-Call Capability Tracking
**Goal:** Epoxy only routes to models that reliably handle tool-calling; silently downgrade if needed.

**Tasks:**
- [ ] Add `ToolCallCapability` enum to `PoolKey` and `ProviderClient`
  ```python
  class ToolCallCapability(str, Enum):
      FULL = "full"              # Supports tools + tool_calls
      PARTIAL = "partial"       # Handles tools but unreliable output
      NONE = "none"             # No tool support
  ```
- [ ] Create capability matrix CSV (models × tool-call support)
  ```csv
  model,provider,tool_calls_capable,streaming_tools,comment
  groq-llama-3.3-70b-versatile,groq,true,true,Fully reliable
  groq-llama-3.1-8b-instant,groq,true,true,Reliable
  ollama-qwen3.5:cloud,ollama,false,false,No tool support
  mistral-large-latest,mistral,true,true,Full support
  ```
- [ ] Update server.py to track capabilities:
  ```python
  @dataclass
  class PoolKey:
      value: str
      provider: str
      model: str
      tool_call_capable: bool = True
      # ... existing fields ...
  ```
- [ ] When `/v1/chat/completions` receives `tools` parameter:
  - Filter healthy keys to only tool-call-capable models
  - If none available, return clear error: `{"error": {"code": "no_tool_models", "message": "No models with tool-call capability are available. Try without tools."}}`

**PR Acceptance Criteria:**
- Tool-call requests route to groq-llama-3.3 or mistral-large
- Non-tool-capable models are skipped
- Unit test: request with tools → only compatible models selected

---

### 2.2 Reasoning Model Priority
**Goal:** Requests with complex reasoning hints route to larger models first.

**Tasks:**
- [ ] Detect reasoning-heavy prompts (keywords: "analyze", "debug", "architecture", "design")
  ```python
  REASONING_KEYWORDS = [
      "analyze", "debug", "architecture", "design", "explain",
      "why", "how", "trade-off", "pros and cons"
  ]
  
  def is_reasoning_task(messages: list) -> bool:
      text = " ".join(m.get("content", "") for m in messages).lower()
      return any(kw in text for kw in REASONING_KEYWORDS)
  ```
- [ ] Reorder provider priority for reasoning tasks:
  - Groq Llama 3.3 70B (best reasoning)
  - Mistral Large (good reasoning)
  - Then others
- [ ] Add `X-Reasoning-Detected: true` header to response
- [ ] Document: "Epoxy auto-detects reasoning tasks and routes smarter"

**PR Acceptance Criteria:**
- Reasoning prompt → Llama 3.3 selected (if available)
- Non-reasoning → can use faster models
- Response header shows detection worked

---

### 2.3 Speed-First Routing for UI Tasks
**Goal:** Autocomplete, chat responses <500ms prefer Groq fast models.

**Tasks:**
- [ ] Add `X-Task-Type` hint from client (optional header):
  ```
  X-Task-Type: autocomplete    # → Groq 8B first
  X-Task-Type: reasoning       # → Groq 70B first
  X-Task-Type: general         # → auto-detect
  ```
- [ ] If no hint, heuristic:
  - `max_tokens < 500` → prefer Groq 8B (fastest)
  - `max_tokens >= 500` → round-robin all
- [ ] Document in API section: "Optional X-Task-Type header for performance hints"

**PR Acceptance Criteria:**
- Short completions use fast models
- Long reasoning uses large models
- Latency telemetry in `/health`

---

### 2.4 Model Availability Matrix
**Goal:** `/v1/models` endpoint returns rich metadata so agents choose wisely.

**Tasks:**
- [ ] Expand model response format:
  ```json
  {
    "id": "groq-llama-3.3-70b-versatile",
    "object": "model",
    "created": 1719216000,
    "owned_by": "groq",
    "capabilities": {
      "tool_calls": true,
      "vision": false,
      "streaming": true,
      "reasoning": true
    },
    "speed": "medium",
    "context_window": 8192,
    "free_tier_monthly_tokens": 500000000,
    "status": "healthy"
  }
  ```
- [ ] Update `/v1/models` to sort by `status` (healthy first) and `capabilities` (tool_calls first if tools requested)

**PR Acceptance Criteria:**
- `/v1/models` returns extended metadata
- Agents can inspect capabilities before routing
- Status reflects actual key health

---

## Phase 3: Lightweight Deployment & Documentation (Week 3-4)

### 3.1 Windows One-Click Installer
**Goal:** Coders on Windows click `.exe`, fill in 3 API keys, start coding.

**Tasks:**
- [ ] Create `installer/build.ps1` (PowerShell builder)
  ```powershell
  # Creates standalone .exe with embedded Python + Epoxy
  # Uses PyInstaller + NSIS
  ```
- [ ] Include 3-step setup wizard:
  1. Add GROQ_API_KEYS (paste key)
  2. Add OLLAMA_API_KEYS (paste key)
  3. Add MISTRAL_API_KEYS (paste key)
  4. Start (launches browser to `http://localhost:8080`)
- [ ] Output: `EpoxySetup-v1.2.17-x64.exe` (~50 MB)
- [ ] Create `docs/WINDOWS_INSTALL.md` with screenshots

**PR Acceptance Criteria:**
- Installer runs on Windows 10+
- Setup wizard works
- Epoxy starts and serves `/health`
- Link in README points to Release page

---

### 3.2 Raspberry Pi Guide
**Goal:** Homelabbers deploy Epoxy on Raspberry Pi 4 (2 GB RAM minimum).

**Tasks:**
- [ ] Create `docs/RASPBERRY_PI.md`:
  ```markdown
  # Running Epoxy on Raspberry Pi
  
  ## Hardware
  - Raspberry Pi 4 (2GB+ RAM) or Pi 5 (recommended)
  - MicroSD 16GB+ (SSD is faster)
  - Power supply 3A+
  
  ## Installation
  1. Flash Raspberry Pi OS Lite (64-bit) to SD card
  2. SSH into Pi
  3. Run: curl -fsSL https://instax-dutta.com/epoxy/install-pi.sh | bash
  
  ## Performance
  - Idle: ~25 MB RAM, 1% CPU
  - Under load: ~80 MB RAM, 40% CPU (single core)
  - Best for: Hosting local dev proxy, CI/CD agent gateway
  ```
- [ ] Create `installer/install-pi.sh`:
  - Auto-detects ARM64
  - Uses system Python
  - Creates systemd service
  - Enables auto-restart on reboot
- [ ] Benchmark: measure RAM, CPU, latency on Pi 4
- [ ] Document: "Run your own 1.7B token/month gateway for $35"

**PR Acceptance Criteria:**
- Install script runs on Pi OS 64-bit
- Epoxy starts via systemd
- Test with real Claude Code/OpenCode from another machine

---

### 3.3 Pterodactyl Egg Refinement
**Goal:** Game server hosters run Epoxy as a service alongside game servers.

**Tasks:**
- [ ] Update `egg-epoxy.json`:
  - Add health check: `curl -s http://localhost:$SERVER_PORT/health`
  - Add auto-startup variables
  - Document: "Zero game server impact; offload AI requests to same Pterodactyl install"
- [ ] Create `docs/PTERODACTYL_GUIDE.md`:
  ```markdown
  # Epoxy on Pterodactyl
  
  Use case: Host AI proxy alongside game servers on same panel.
  
  1. Download egg-epoxy.json
  2. Admin → Nests → Import Egg
  3. Create new server → Egg: Epoxy
  4. File Manager → Edit .env → Add API keys
  5. Start server
  6. Point Claude Code at http://<panel-ip>:allocated-port/v1
  ```
- [ ] Clarify: "Doesn't conflict with game ports; uses unique allocation"

**PR Acceptance Criteria:**
- Egg imports into Pterodactyl
- Server starts without errors
- `/health` responds

---

### 3.4 Docker Multi-Arch Optimization
**Goal:** `docker run` on x86_64, ARM64, even ARM32 without friction.

**Tasks:**
- [ ] Update Dockerfile:
  ```dockerfile
  FROM python:3.11-slim-bullseye
  # Optimize for size: <100 MB image
  # Multi-stage: build → runtime
  ```
- [ ] Update docker-compose.yml:
  ```yaml
  services:
    epoxy:
      build:
        context: .
        platforms:
          - linux/amd64
          - linux/arm64
          - linux/arm/v7
      image: ghcr.io/instax-dutta/epoxy:latest
  ```
- [ ] Add CI workflow: `.github/workflows/docker-build.yml`
  - Builds multi-arch on every tag
  - Publishes to GHCR
  - Test image size: should be <150 MB
- [ ] Document: "Same `docker run` works on Mac, Linux, ARM servers, Synology NAS"

**PR Acceptance Criteria:**
- Docker image builds for linux/amd64, linux/arm64
- Image runs: `docker run ghcr.io/instax-dutta/epoxy:latest`
- Size: <200 MB

---

## Phase 4: Dashboard & Observability (Week 4-5)

### 4.1 Lightweight Web Dashboard
**Goal:** Minimal React app (vanilla JS is fine) showing keys, health, recent requests.

**Tasks:**
- [ ] Create `dashboard/` folder:
  ```
  dashboard/
    index.html          # Single page
    styles.css          # Minimal styles
    app.js             # Vanilla JS or lightweight preact
    ws.js              # WebSocket for live updates
  ```
- [ ] Pages:
  1. **Health** — Key status per provider, healthy count, total tokens consumed
  2. **Recent Requests** — Last 50 requests: timestamp, model, latency, status
  3. **Playground** — Send test requests, see which provider routed it
  4. **Settings** — Manage API keys (encrypted in browser, sent to server over HTTPS)
- [ ] Example markup:
  ```html
  <!DOCTYPE html>
  <html>
  <head>
    <title>Epoxy Dashboard</title>
    <link rel="stylesheet" href="styles.css">
  </head>
  <body>
    <div id="app">
      <h1>Epoxy Proxy</h1>
      <nav>
        <a href="#health">Health</a>
        <a href="#requests">Requests</a>
        <a href="#playground">Playground</a>
      </nav>
      <div id="content"></div>
    </div>
    <script src="app.js"></script>
  </body>
  </html>
  ```
- [ ] Serve from Python: 
  ```python
  @app.get("/")
  async def dashboard():
      return FileResponse("dashboard/index.html")
  ```
- [ ] Estimate size: <50 KB (uncompressed)

**PR Acceptance Criteria:**
- Dashboard loads at `http://localhost:8080/`
- Health page shows key status
- Playground sends test requests
- Recent requests log works

---

### 4.2 Request Telemetry & Logging
**Goal:** Every request gets logged: timestamp, model, latency, tokens, status.

**Tasks:**
- [ ] Add logging middleware:
  ```python
  @app.middleware("http")
  async def log_request(request: Request, call_next):
      start = time.time()
      response = await call_next(request)
      duration = time.time() - start
      
      logger.info({
          "timestamp": start,
          "method": request.method,
          "path": request.url.path,
          "model": request.query_params.get("model", "unknown"),
          "status": response.status_code,
          "duration_ms": duration * 1000,
          "provider": response.headers.get("X-Routed-Via", "unknown"),
      })
      return response
  ```
- [ ] Store in SQLite (in-memory ring buffer, auto-rotate after 100 requests):
  ```sql
  CREATE TABLE request_log (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    model TEXT,
    provider TEXT,
    latency_ms REAL,
    status_code INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    error TEXT
  );
  ```
- [ ] Add `/api/requests?limit=50` endpoint:
  ```json
  [
    {
      "timestamp": 1719216000.123,
      "model": "groq-llama-3.3-70b-versatile",
      "provider": "groq",
      "latency_ms": 245,
      "status": 200,
      "tokens_in": 50,
      "tokens_out": 125
    }
  ]
  ```

**PR Acceptance Criteria:**
- Requests are logged
- `/api/requests` returns last 50
- Dashboard displays them in real-time (polling or WebSocket)

---

### 4.3 Analytics Endpoints
**Goal:** `/api/analytics` shows token burn rate, provider health, SLA metrics.

**Tasks:**
- [ ] Add endpoints:
  ```python
  GET /api/analytics?window=24h  # 24 hours, 7 days, 30 days
  
  Response:
  {
    "window": "24h",
    "total_requests": 1250,
    "total_tokens_in": 125000,
    "total_tokens_out": 87000,
    "success_rate": 99.2,
    "avg_latency_ms": 380,
    "providers": {
      "groq": {
        "requests": 750,
        "tokens_out": 52000,
        "latency_ms": 245
      },
      "ollama": { ... },
      "mistral": { ... }
    },
    "errors": {
      "429": 8,
      "401": 1,
      "timeout": 2
    }
  }
  ```
- [ ] Dashboard displays simple charts:
  - Requests per hour (bar chart)
  - Provider breakdown (pie chart)
  - Token burn rate (line graph)

**PR Acceptance Criteria:**
- `/api/analytics` returns valid JSON
- Dashboard renders charts
- 24h/7d/30d windows work

---

### 4.4 WebSocket Live Updates
**Goal:** Dashboard shows real-time request flow without polling.

**Tasks:**
- [ ] Add WebSocket endpoint (FastAPI):
  ```python
  from fastapi import WebSocket
  
  @app.websocket("/ws/events")
  async def websocket_endpoint(websocket: WebSocket):
      await websocket.accept()
      try:
          while True:
              # Broadcast request events to all connected clients
              event = {
                  "type": "request",
                  "model": ...,
                  "latency": ...,
                  "status": ...
              }
              await websocket.send_json(event)
              await asyncio.sleep(0.1)
      except:
          pass
  ```
- [ ] Dashboard JS:
  ```javascript
  const ws = new WebSocket('ws://localhost:8080/ws/events');
  ws.onmessage = (e) => {
    const event = JSON.parse(e.data);
    updateDashboard(event);
  };
  ```

**PR Acceptance Criteria:**
- WebSocket connects
- Real-time events flow to dashboard
- Charts update without page reload

---

## Phase 5: Documentation & Community (Week 5-6)

### 5.1 Comprehensive README Restructure
**Goal:** Lead with agent support; show actual use cases.

**Tasks:**
- [ ] Rewrite README sections:
  ```markdown
  # Epoxy: Lightweight AI Agent Proxy
  
  **Use Epoxy as your AI agent's brain. Groq + Ollama + Mistral pooled into one endpoint.**
  
  ### Works With These Agents
  - ✅ Claude Code (Anthropic)
  - ✅ OpenCode (Vercel)
  - ✅ Kilo Code
  - ✅ Cline (VSCode + Claude)
  - ✅ Continue (IDE autocomplete)
  
  ### One Command to Start
  
  **Windows:** `EpoxySetup.exe` (click, fill 3 keys, done)
  **Mac/Linux:** `docker run -p 8080:8080 ghcr.io/instax-dutta/epoxy:latest`
  **Raspberry Pi:** `curl ... | bash`
  
  ### Features
  - 3 free-tier providers pooled (~800M tokens/month free)
  - Tool-calling optimized (routes to Llama 3.3 70B first)
  - <50 MB memory footprint
  - 30-second deploy on Windows, Raspberry Pi, Docker, Pterodactyl
  - Live dashboard + analytics
  
  ### Quick Example
  
  # Set your API keys
  GROQ_API_KEYS="gsk_..." OLLAMA_API_KEYS="..." python server.py
  
  # Use from Claude Code
  export ANTHROPIC_BASE_URL=http://localhost:8080
  export ANTHROPIC_AUTH_TOKEN=any-string
  claude
  ```
- [ ] Reorder sections: Quickstart → Agent Frameworks → Features → Deploy
- [ ] Remove technical jargon; add benefit statements

**PR Acceptance Criteria:**
- README is agent-focused
- "Works With" section updated with all 5+ frameworks
- Deploy instructions for Windows, Raspberry Pi, Docker, Pterodactyl

---

### 5.2 Agent Setup Guides
**Goal:** Every agent gets a dedicated guide file.

**Tasks:**
- [ ] Create `docs/` directory:
  ```
  docs/
    CLAUDE_CODE.md       # Step-by-step with screenshots
    OPENCODE.md          # Step-by-step with screenshots
    KILO_CODE.md         # Step-by-step with screenshots
    CLINE.md             # Step-by-step with screenshots
    CONTINUE.md          # Step-by-step with screenshots
    API_REFERENCE.md     # Full endpoint docs
    DEPLOYMENT.md        # Windows, Raspberry Pi, Docker, Pterodactyl
    TROUBLESHOOTING.md   # Common issues & fixes
    CONTRIBUTING.md      # How to add providers, features
  ```
- [ ] Each guide includes:
  - Prerequisites
  - Step-by-step instructions
  - Screenshots (if possible)
  - Testing checklist
  - Troubleshooting
- [ ] Example: `docs/CLAUDE_CODE.md`
  ```markdown
  # Using Epoxy with Claude Code
  
  Claude Code (the official Anthropic CLI tool) lets you pair-program with Claude
  using your terminal. Epoxy lets you use free Groq/Ollama models instead of paid Claude.
  
  ## Setup (2 minutes)
  
  1. Start Epoxy
  2. Export env vars (macOS/Linux):
     ```bash
     export ANTHROPIC_BASE_URL=http://localhost:8080
     export ANTHROPIC_AUTH_TOKEN=any-string
     claude
     ```
  
  3. Start a task:
     ```
     claude "write a CLI to-do app in Rust"
     ```
  
  4. Claude Code talks to your Epoxy proxy, which routes to Groq/Ollama
  
  ## Troubleshooting
  
  ### "Connection refused"
  - Make sure Epoxy is running: `curl http://localhost:8080/health`
  
  ### "Invalid API key"
  - ANTHROPIC_AUTH_TOKEN can be any string; Epoxy doesn't validate it
  ```

**PR Acceptance Criteria:**
- All 5+ agent guides written
- Each guide is 200-300 words
- Screenshots included
- Copy-paste commands work

---

### 5.3 API Reference Documentation
**Goal:** Developers understand every endpoint and parameter.

**Tasks:**
- [ ] Create `docs/API_REFERENCE.md`:
  ```markdown
  # Epoxy API Reference
  
  ## Authentication
  - No authentication by default (local-only)
  - If exposing to internet, use EPOXY_API_KEY env var
  
  ## Endpoints
  
  ### GET /health
  Returns pool status for each provider.
  
  ```json
  {
    "status": "ok",
    "providers": {
      "groq": {
        "total": 3,
        "healthy": 2,
        "strategy": "round_robin"
      }
    }
  }
  ```
  
  ### POST /v1/chat/completions
  OpenAI-compatible chat completions.
  
  Request:
  ```json
  {
    "model": "groq-llama-3.3-70b-versatile",
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": false,
    "tools": [...]  // optional
  }
  ```
  
  Response:
  ```json
  {
    "id": "chatcmpl-...",
    "choices": [{
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }],
    "usage": {
      "prompt_tokens": 10,
      "completion_tokens": 50
    }
  }
  ```
  
  Headers (response):
  - `X-Routed-Via: groq/llama-3.3-70b-versatile`
  - `X-Task-Type: reasoning` (if detected)
  ```

**PR Acceptance Criteria:**
- All endpoints documented
- Examples for each
- Response schemas shown
- Custom headers explained

---

### 5.4 Deployment Guide
**Goal:** One document covers all deployment targets.

**Tasks:**
- [ ] Create `docs/DEPLOYMENT.md`:
  ```markdown
  # Deploying Epoxy
  
  ## Windows
  - Download EpoxySetup.exe from Releases
  - Click → follow wizard
  - Opens http://localhost:8080 automatically
  
  ## Raspberry Pi
  - `curl ... | bash` (automated installer)
  - Runs as systemd service
  - Start/stop: `systemctl start/stop epoxy`
  
  ## Docker (Mac/Linux/Windows WSL)
  - `docker run -p 8080:8080 ghcr.io/instax-dutta/epoxy:latest`
  - Multi-arch: works on ARM64, x86_64, even ARM32 (Synology, old Pi)
  
  ## Pterodactyl
  - Import egg-epoxy.json
  - Create server
  - Add keys via File Manager
  - Start
  
  ## Manual (Python)
  - git clone + pip install -r requirements.txt
  - python server.py
  
  ## Performance
  - Windows 11 (4GB RAM): Idle ~30 MB, under load ~100 MB
  - Raspberry Pi 4 (2GB): Idle ~25 MB, under load ~80 MB
  - Docker: Same footprint
  ```

**PR Acceptance Criteria:**
- Deployment document complete
- All 5 methods tested
- Performance benchmarks included

---

### 5.5 Troubleshooting Guide
**Goal:** Users self-diagnose 90% of issues.

**Tasks:**
- [ ] Create `docs/TROUBLESHOOTING.md`:
  ```markdown
  # Troubleshooting Epoxy
  
  ## "Connection refused" when connecting from an agent
  
  **Symptom:** Claude Code, OpenCode, etc. can't reach Epoxy
  
  **Diagnosis:**
  - Is Epoxy running? Check: curl http://localhost:8080/health
  - Did you use http://localhost or http://127.0.0.1?
  - Check firewall: is port 8080 open?
  
  **Fix:**
  - Make sure .env has valid keys
  - Restart Epoxy
  - Check: http://dashboard:8080 loads
  
  ## "All keys exhausted" error
  
  **Symptom:** Requests fail with 429 and "all keys on cooldown"
  
  **Diagnosis:**
  - You hit rate limits on all your keys
  - Check /health → how many keys are "rate_limited"?
  
  **Fix:**
  - Wait 1 hour (rate limits cool down)
  - Add more keys from other providers (OpenRouter, Cohere, etc.)
  - For production: use FreeLLMAPI Premium or paid providers
  
  ## "Invalid API key" from provider
  
  **Symptom:** Requests fail with 401
  
  **Diagnosis:**
  - Provider API key is wrong, expired, or deleted
  
  **Fix:**
  - Check your .env: copy key from provider website
  - Regenerate key in provider dashboard
  - Restart Epoxy after changing .env
  
  ## Latency is slow
  
  **Symptom:** Requests take >2 seconds
  
  **Diagnosis:**
  - You're routing to Ollama Cloud (slowest)
  - Your internet is slow
  - Provider is having issues
  
  **Fix:**
  - Prioritize Groq in fallback chain (fastest)
  - Check: /api/analytics to see which provider is slow
  - Try a different model
  ```

**PR Acceptance Criteria:**
- Guide covers 5-10 common issues
- Solutions are actionable
- Includes diagnostic commands

---

## Phase 6: Advanced Features (Week 6-7)

### 6.1 Cost Tracking & Quota Warnings
**Goal:** Users see estimated burn rate and warnings when running low.

**Tasks:**
- [ ] Add token counting per provider:
  ```python
  TOKEN_COSTS = {  # Example, adjust per provider
      "groq": {"in": 0, "out": 0},  # Free (limited quota)
      "ollama": {"in": 0, "out": 0},
      "mistral": {"in": 0.2, "out": 1.0},  # per 1M tokens
  }
  
  @dataclass
  class PoolKey:
      free_tier_tokens_monthly: int = 500_000_000  # Groq free tier
      tokens_used_this_month: int = 0
  ```
- [ ] Add `/api/quota` endpoint:
  ```json
  {
    "provider": "groq",
    "free_tier_tokens_monthly": 500000000,
    "tokens_used_this_month": 125000000,
    "tokens_remaining": 375000000,
    "estimated_days_remaining": 23
  }
  ```
- [ ] Dashboard displays quota bar with warning colors

**PR Acceptance Criteria:**
- Token counting works
- `/api/quota` endpoint returns expected data
- Dashboard shows quota bar

---

### 6.2 Request Caching
**Goal:** Identical requests within 5 min return cached response (no token burn).

**Tasks:**
- [ ] Implement simple in-memory cache:
  ```python
  from functools import lru_cache
  import hashlib
  
  def cache_key(model, messages) -> str:
      # Hash model + messages to create cache key
      return hashlib.sha256(f"{model}:{json.dumps(messages)}".encode()).hexdigest()
  
  request_cache = {}  # {"cache_key": (timestamp, response)}
  
  # Before routing:
  key = cache_key(model, messages)
  if key in request_cache:
      age = time.time() - request_cache[key][0]
      if age < 300:  # 5 min
          return request_cache[key][1]
  ```
- [ ] Add header to cached responses: `X-Cache: HIT`
- [ ] Document: "Ideal for IDE autocomplete (same code → same suggestion)"

**PR Acceptance Criteria:**
- Identical requests use cache
- Cache expires after 5 minutes
- Header shows cache hit/miss

---

### 6.3 Sticky Sessions (Multi-Turn Conversations)
**Goal:** Same client → same model for 30 min (avoid hallucination spikes from model switches).

**Tasks:**
- [ ] Track session by header `X-Session-Id` or first message SHA:
  ```python
  import hashlib
  
  def get_session_id(request_body, client_ip):
      # Use X-Session-Id header if provided, else create one
      session_header = request.headers.get("X-Session-Id")
      if session_header:
          return session_header
      
      # Hash first message + client IP
      first_msg = request_body["messages"][0]["content"] if request_body["messages"] else ""
      return hashlib.sha256(f"{client_ip}:{first_msg}".encode()).hexdigest()
  
  SESSION_AFFINITY = {}  # {session_id: (model, timestamp)}
  ```
- [ ] On subsequent requests from same session:
  - If model is healthy and within 30 min → use same model
  - Otherwise → pick new model and record it
- [ ] Add response header: `X-Session-Id: <id>`, `X-Session-Affinity: true`

**PR Acceptance Criteria:**
- Sticky sessions work
- Same client → same model for 30 min
- Model switches when old model fails

---

### 6.4 Custom OpenAI-Compatible Provider Support
**Goal:** Users can add local Ollama, llama.cpp, LM Studio, or any OpenAI-compat endpoint.

**Tasks:**
- [ ] Add custom provider to PoolKey:
  ```python
  @dataclass
  class CustomProvider:
      base_url: str           # http://localhost:11434/v1
      label: str             # "Local Ollama"
      api_key: str = ""      # optional
      models: list = None    # [{"id": "llama3.1:8b", "name": "..."}]
  ```
- [ ] Dashboard "Add Custom Provider" form:
  - Base URL input
  - Optional API key
  - Auto-detect available models via `/v1/models`
- [ ] Route requests to custom provider like any other
- [ ] Use case: "I have Ollama running locally; use it first, then fall back to cloud"

**PR Acceptance Criteria:**
- Custom provider can be added via dashboard
- Requests route to custom provider
- Fallback to cloud providers works

---

## Phase 7: Testing & Release (Week 7-8)

### 7.1 Integration Tests
**Goal:** Automated verification that all agent frameworks work.

**Tasks:**
- [ ] Create `tests/test_agents.py`:
  ```python
  def test_claude_code_anthropic_api():
      """Verify /v1/messages works for Claude Code"""
      response = client.post("/v1/messages", json={
          "model": "claude-sonnet",
          "max_tokens": 100,
          "messages": [{"role": "user", "content": "hi"}]
      })
      assert response.status_code == 200
  
  def test_openai_compatible_chat():
      """Verify /v1/chat/completions works"""
      response = client.post("/v1/chat/completions", json={
          "model": "groq-llama-3.1-8b-instant",
          "messages": [{"role": "user", "content": "hi"}]
      })
      assert response.status_code == 200
  
  def test_tool_calling_routes_to_capable_model():
      """Verify tool-call requests only route to capable models"""
      response = client.post("/v1/chat/completions", json={
          "model": "auto",
          "messages": [{"role": "user", "content": "hi"}],
          "tools": [{"type": "function", "function": {"name": "test"}}]
      })
      assert response.status_code == 200
      routed_via = response.headers.get("X-Routed-Via")
      assert "llama-3.3" in routed_via or "mistral" in routed_via
  ```
- [ ] Run tests before every release
- [ ] CI/CD: GitHub Actions to run tests on every push

**PR Acceptance Criteria:**
- Tests pass locally
- CI/CD pipeline green
- Test coverage for all agent frameworks

---

### 7.2 Performance Benchmarking
**Goal:** Document latency, memory, throughput before release.

**Tasks:**
- [ ] Create `benchmark.py`:
  ```python
  import time
  import psutil
  
  def benchmark_latency():
      """Measure avg latency over 100 requests"""
      times = []
      for _ in range(100):
          start = time.time()
          response = client.post("/v1/chat/completions", json={...})
          times.append(time.time() - start)
      return sum(times) / len(times)
  
  def benchmark_memory():
      """Measure peak memory"""
      process = psutil.Process()
      initial = process.memory_info().rss / 1024 / 1024
      # Run 100 requests...
      peak = process.memory_info().rss / 1024 / 1024
      return peak - initial
  ```
- [ ] Document results:
  ```markdown
  ## Benchmarks (v1.3.0)
  
  - Avg latency: 380ms (Groq 8B)
  - Peak memory: 85 MB (Raspberry Pi 4)
  - Throughput: 1000+ req/min
  - Idle memory: 30 MB
  ```

**PR Acceptance Criteria:**
- Benchmarks run successfully
- Results documented in RELEASES.md or BENCHMARKS.md

---

### 7.3 Release Checklist
**Goal:** Consistent, high-quality releases.

**Tasks:**
- [ ] Create `RELEASE_CHECKLIST.md`:
  ```markdown
  # Release Checklist
  
  Before every release:
  - [ ] All tests pass
  - [ ] Benchmarks within expected range
  - [ ] README updated with new features
  - [ ] CHANGELOG.md updated
  - [ ] Version bumped in server.py (v1.2.17 → v1.3.0)
  - [ ] Docker image builds for amd64/arm64
  - [ ] Windows .exe built and tested
  - [ ] Raspberry Pi install script tested
  - [ ] Tag pushed: git tag v1.3.0 && git push origin v1.3.0
  ```
- [ ] Use this for every release

**PR Acceptance Criteria:**
- Checklist created
- Followed for every release

---

### 7.4 Release Notes Template
**Goal:** Clear, user-friendly release notes.

**Tasks:**
- [ ] Create template `RELEASE_TEMPLATE.md`:
  ```markdown
  # Epoxy v1.3.0
  
  ## ✨ New Features
  - Anthropic Messages API support (Claude Code now works!)
  - Tool-call routing (automatically uses Llama 3.3 70B)
  - Live dashboard with analytics
  - Custom OpenAI-compatible provider support
  
  ## 🐛 Fixes
  - Fixed memory leak in request logging
  - Improved error messages for rate-limited keys
  
  ## 📦 Downloads
  - [Windows Installer](link)
  - [Docker](docker pull ghcr.io/instax-dutta/epoxy:v1.3.0)
  - [Source Code](tar.gz)
  
  ## 🙏 Thanks
  - @contributor-1 for feature X
  - @contributor-2 for bug fix Y
  ```

**PR Acceptance Criteria:**
- Template created
- Used for every release

---

## Phase 8: Community & Maintenance (Ongoing)

### 8.1 GitHub Issues Triage
**Goal:** Respond to issues within 24 hours.

**Tasks:**
- [ ] Create issue templates: `.github/ISSUE_TEMPLATE/`
  - Bug report
  - Feature request
  - Question
- [ ] Triage process:
  1. Label: `bug`, `feature`, `documentation`, `help-wanted`
  2. Respond within 24 hours
  3. Link related issues
  4. Close resolved issues within 1 week

---

### 8.2 Contributing Guide
**Goal:** Lower barrier for community PRs.

**Tasks:**
- [ ] Create `CONTRIBUTING.md`:
  ```markdown
  # Contributing to Epoxy
  
  ## Setup
  ```bash
  git clone https://github.com/instax-dutta/epoxy
  cd epoxy
  pip install -r requirements.txt
  python server.py
  ```
  
  ## PR Process
  1. Fork & branch (`git checkout -b feature/my-feature`)
  2. Make changes
  3. Test locally
  4. Push & open PR
  5. Await review (48 hours)
  
  ## Areas We Need Help
  - Adding new providers (Cohere, OpenRouter, etc.)
  - Dashboard improvements
  - Documentation
  - Platform support (more ARM targets, Windows arm64, etc.)
  ```

**PR Acceptance Criteria:**
- Guide published
- Issue templates created

---

### 8.3 Discord/Community Channel
**Goal:** Real-time support and feature discussion.

**Tasks:**
- [ ] Create Discord server (free)
- [ ] Channels:
  - #announcements (releases, breaking changes)
  - #help (support questions)
  - #feature-requests (discussion)
  - #showcase (user projects)
- [ ] Link in README
- [ ] Check daily for 15 min

---

## Success Metrics & KPIs

### 3-Month Goals
| Metric | Target | Measurement |
|--------|--------|-------------|
| GitHub Stars | 500–1,000 | github.com/instax-dutta/epoxy |
| PyPI Downloads | 5,000+/month | pypistats.org |
| Docker Pulls | 10,000+/month | hub.docker.com |
| Agent Framework Support | 5+ | Claude Code, OpenCode, Kilo Code, Cline, Continue |
| Deployment Targets | 6+ | Windows, Mac, Linux, Raspberry Pi, Pterodactyl, Docker |
| Dashboard Completion | 100% | All pages functional |
| Documentation | Complete | All guides written & verified |

### 6-Month Goals
| Metric | Target | Measurement |
|--------|--------|-------------|
| GitHub Stars | 2,000+ | github.com/instax-dutta/epoxy |
| Community Contributors | 10+ | active PRs & issues |
| Supported Providers | 6+ (vs. current 3) | Groq, Ollama, Mistral, Google, OpenRouter, Cohere, etc. |
| Non-Docker Deployment % | 30% | Windows installers, Pi scripts, manual deploys |
| Uptime SLA Documentation | Published | clear limitations & expectations |

---

## Implementation Order (Priority)

### Week 1–2 (Agent Framework Integration)
1. **Claude Code** (most users from your target audience)
2. **OpenCode** (Vercel backing, growing user base)
3. **Kilo Code** (emerging, friendly creator)
4. Cline (VSCode extension, large audience)
5. Continue (IDE autocomplete use case)

### Week 2–3 (Tool-Call Efficiency)
1. **Tool-call capability matrix** (critical for agent reliability)
2. **Reasoning model priority** (improves logic tasks)
3. **Speed-first routing** (improves autocomplete latency)

### Week 3–4 (Deployment & Documentation)
1. **Windows installer** (biggest pain point for non-devs)
2. **Raspberry Pi guide** (homelabber market)
3. **Docker multi-arch** (lowest-barrier deploy)
4. **README overhaul** (marketing → "agent proxy")

### Week 4–5 (Dashboard & Observability)
1. **Lightweight web dashboard** (users expect it)
2. **Request telemetry** (debugging aid)
3. **Analytics endpoints** (quota tracking)

### Week 5–6 (Documentation & Community)
1. **API reference** (developers need it)
2. **Deployment guide** (reduce support burden)
3. **Troubleshooting guide** (self-service support)
4. **Agent setup guides** (reduces friction)

### Week 6–7 (Advanced Features)
1. **Cost tracking** (users care about burn rate)
2. **Request caching** (improves feel)
3. **Sticky sessions** (improves reliability)
4. **Custom provider support** (flexibility)

### Week 7–8 (Testing & Release)
1. **Integration tests** (confidence)
2. **Performance benchmarking** (documentation)
3. **Release pipeline** (quality control)

---

## Coding Agent Instructions

### For Implementing Phase 1–2 (Weeks 1–3)

**Goal:** Full agent framework support + tool-call routing

**Acceptance Criteria:**
1. ✅ Claude Code connects to Epoxy and completes a multi-turn coding task
2. ✅ OpenCode runs with Epoxy provider and completes autocomplete
3. ✅ Kilo Code connects and completes a task
4. ✅ Cline connects and completes a VSCode extension task
5. ✅ Continue autocomplete works
6. ✅ Tool-call requests route only to Llama 3.3 70B or Mistral Large
7. ✅ `/v1/models` returns `tool_calls: true/false` capability
8. ✅ All documentation updated in README + `docs/AGENT_*.md` files

**Files to Modify/Create:**
```
server.py                           # Add /v1/messages, tool-call routing
dashboard/index.html                # (Week 4) Minimal UI
dashboard/app.js                    # (Week 4) JS logic
docs/CLAUDE_CODE.md                 # New
docs/OPENCODE.md                    # New
docs/KILO_CODE.md                   # New
docs/CLINE.md                        # New
docs/CONTINUE.md                    # New
docs/AGENT_COMPATIBILITY.md         # New
docs/API_REFERENCE.md               # New
README.md                            # Restructure
tests/test_agents.py                # New
```

**Testing Before Commit:**
```bash
# 1. Start Epoxy
python server.py

# 2. Test Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8080
export ANTHROPIC_AUTH_TOKEN=any-string
claude "write a python hello world"

# 3. Test OpenCode
opencode  # Check provider loads

# 4. Test Cline
# In VSCode with Cline extension, point to http://localhost:8080/v1

# 5. Test tool-calling
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "test"}],
    "tools": [{"type": "function", "function": {"name": "test"}}]
  }'
# Verify X-Routed-Via header shows llama-3.3 or mistral-large
```

---

## Ongoing Maintenance Plan

### Weekly
- [ ] Check GitHub Issues (respond to new issues)
- [ ] Monitor Discord/community for questions
- [ ] Run test suite

### Monthly
- [ ] Review metrics (stars, downloads, issues)
- [ ] Update `CHANGELOG.md`
- [ ] Review dependency updates (fastapi, httpx, python-dotenv)
- [ ] Test on latest Raspberry Pi OS
- [ ] Test Windows installer on Windows 11

### Quarterly
- [ ] Major release (Phase → new features)
- [ ] Provider audit (test all keys still work)
- [ ] Security review (dependency vulns, encryption)

---

## Risk Mitigation

### Risk: FreeLLMAPI catches up with more features
**Mitigation:** Stay focused on "lightweight for agents" niche. Don't try to match every feature.

### Risk: Providers change rate limits / shut down free tiers
**Mitigation:** Monitor provider blogs. Add fallback logic. Document: "Free tiers can change; use paid providers for production."

### Risk: Community doesn't adopt despite effort
**Mitigation:** Validate with early users (via Discord, GitHub Issues). Adjust roadmap based on feedback.

### Risk: Burnout from maintaining alone
**Mitigation:** Aim for 70% feature-complete by week 6, then pause. Accept "good enough" over "perfect."

---

## Final Notes for Coding Agents

**Tone:** Be pragmatic, not perfectionist. Epoxy's strength is **simplicity**. Every feature added should have a clear "why" (e.g., "agents need this to work"). If you're unsure, skip it.

**Testing:** Test *actually* with Claude Code, OpenCode, etc. Not just unit tests. Real agent feedback matters more.

**Documentation:** Users read docs more than code. Invest here.

**Community:** Respond to early users. Their feedback is gold.

**Release cadence:** Small, frequent releases (v1.2 → v1.3 → v1.4) beat massive rewrites.

---

**Status:** Ready for Week 1 implementation. Start with Phase 1.1 (Claude Code). Good luck! 🚀

