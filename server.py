import os
import json
import time
import uuid
import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv
import httpx

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)
_last_env_mtime: float = ENV_PATH.stat().st_mtime if ENV_PATH.exists() else 0
_env_reload_lock = asyncio.Lock()

# ─────────────────────────────────────────────
# Hermes Agent Free-Tier Proxy
#
# Point Hermes Agent at this proxy to pool
# multiple free-tier API keys (Groq + Ollama
# Cloud) behind a single OpenAI-compatible
# endpoint. Key rotation and cooldown handling
# are automatic.
#
# Hermes config.yaml:
#   custom_providers:
#     free-pool:
#       base_url: http://127.0.0.1:8080
#
# Then use /model groq-llama-3.1-8b-instant
# or /model ollama-deepseek-v3.1 in Hermes.
#
# Strategies (set via GROQ_POOL_STRATEGY /
# OLLAMA_POOL_STRATEGY env vars):
#   fill_first   — drain the first healthy key before moving on
#   round_robin  — cycle evenly across all healthy keys
#   least_used   — pick the key with fewest requests
#   random       — pick randomly among healthy keys
#
# Per-key state:
#   ok           — healthy, ready for use
#   rate_limited — 429, cooldown 1h
#   exhausted    — billing/402, cooldown 24h
#   auth_error   — 401, rotate immediately
#
# Flow per call:
#   1. select() a healthy key
#   2. on 429: retry same key once; second 429 → mark rate_limited → rotate
#   3. on 402: mark exhausted → rotate immediately
#   4. on 401: mark auth_error → rotate immediately
#   5. all keys unhealthy → raise AllExhausted
# ─────────────────────────────────────────────

class PoolStrategy(str, Enum):
    FILL_FIRST = "fill_first"
    ROUND_ROBIN = "round_robin"
    LEAST_USED = "least_used"
    RANDOM = "random"

class KeyStatus(str, Enum):
    OK = "ok"
    RATE_LIMITED = "rate_limited"
    EXHAUSTED = "exhausted"
    AUTH_ERROR = "auth_error"

COOLDOWN_SECONDS = {
    KeyStatus.RATE_LIMITED: 3600,
    KeyStatus.EXHAUSTED: 86400,
    KeyStatus.AUTH_ERROR: 0,
}

@dataclass
class PoolKey:
    value: str
    status: KeyStatus = KeyStatus.OK
    request_count: int = 0
    cooldown_until: float = 0
    has_retried_429: bool = False

    @property
    def is_healthy(self) -> bool:
        if self.status == KeyStatus.OK:
            return True
        if self.status in (KeyStatus.RATE_LIMITED, KeyStatus.EXHAUSTED):
            return time.monotonic() >= self.cooldown_until
        return False

    def mark_ok(self):
        self.status = KeyStatus.OK
        self.cooldown_until = 0
        self.has_retried_429 = False

    def mark_rate_limited(self):
        self.status = KeyStatus.RATE_LIMITED
        self.cooldown_until = time.monotonic() + COOLDOWN_SECONDS[KeyStatus.RATE_LIMITED]

    def mark_exhausted(self):
        self.status = KeyStatus.EXHAUSTED
        self.cooldown_until = time.monotonic() + COOLDOWN_SECONDS[KeyStatus.EXHAUSTED]

    def mark_auth_error(self):
        self.status = KeyStatus.AUTH_ERROR
        self.cooldown_until = time.monotonic() + COOLDOWN_SECONDS[KeyStatus.AUTH_ERROR]


class CredentialPool:
    def __init__(self, name: str, keys: list[str], strategy: PoolStrategy = PoolStrategy.ROUND_ROBIN):
        self.name = name
        self._lock = asyncio.Lock()
        self._strategy = strategy
        self._keys = [PoolKey(value=k) for k in keys]
        self._round_robin_index = 0

    @property
    def total_keys(self) -> int:
        return len(self._keys)

    @property
    def healthy_keys(self) -> int:
        return sum(1 for k in self._keys if k.is_healthy)

    @property
    def strategy(self) -> PoolStrategy:
        return self._strategy

    def set_strategy(self, strategy: PoolStrategy):
        self._strategy = strategy

    async def select(self) -> PoolKey | None:
        async with self._lock:
            healthy = [k for k in self._keys if k.is_healthy]
            if not healthy:
                return None

            if self._strategy == PoolStrategy.FILL_FIRST:
                key = healthy[0]
            elif self._strategy == PoolStrategy.ROUND_ROBIN:
                candidates = sorted(healthy, key=lambda k: self._keys.index(k))
                idx = self._round_robin_index % len(candidates)
                self._round_robin_index = (self._round_robin_index + 1) % len(self._keys)
                key = candidates[idx]
            elif self._strategy == PoolStrategy.LEAST_USED:
                key = min(healthy, key=lambda k: k.request_count)
            elif self._strategy == PoolStrategy.RANDOM:
                key = random.choice(healthy)
            else:
                key = healthy[0]

            key.request_count += 1
            return key

    async def snapshot_current_key(self) -> str | None:
        async with self._lock:
            if not self._keys:
                return None
            key = self._keys[self._round_robin_index % len(self._keys)]
            return key.value

    async def select_for_retry(self, failed_key: PoolKey) -> PoolKey | None:
        async with self._lock:
            healthy = [k for k in self._keys if k.is_healthy and k is not failed_key]
            if not healthy:
                return None
            key = healthy[0]
            key.request_count += 1
            return key

    async def mark_success(self, key: PoolKey):
        async with self._lock:
            key.mark_ok()

    async def mark_error(self, key: PoolKey, status_code: int):
        async with self._lock:
            if status_code == 429:
                if key.has_retried_429:
                    key.mark_rate_limited()
                else:
                    key.has_retried_429 = True
            elif status_code == 402:
                key.mark_exhausted()
            elif status_code == 401:
                key.mark_auth_error()
            else:
                pass

    async def all_exhausted(self) -> bool:
        async with self._lock:
            return all(not k.is_healthy for k in self._keys)

    def get_status(self) -> dict:
        return {
            "total": self.total_keys,
            "healthy": self.healthy_keys,
            "strategy": self.strategy.value,
            "keys": [
                {
                    "label": f"...{k.value[-6:]}",
                    "status": k.status.value,
                    "request_count": k.request_count,
                }
                for k in self._keys
            ],
        }


# ─────────────────────────────────────────────
# API Key Parsing
# ─────────────────────────────────────────────

def _parse_keys(env_var: str) -> list[str]:
    raw = os.environ.get(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _resolve_strategy(name: str) -> PoolStrategy:
    raw = os.environ.get(f"{name}_POOL_STRATEGY", "round_robin").lower()
    try:
        return PoolStrategy(raw)
    except ValueError:
        return PoolStrategy.ROUND_ROBIN


# ─────────────────────────────────────────────
# Provider Pools
# ─────────────────────────────────────────────

groq_pool = CredentialPool(
    "groq",
    _parse_keys("GROQ_API_KEYS"),
    _resolve_strategy("GROQ"),
)
ollama_pool = CredentialPool(
    "ollama",
    _parse_keys("OLLAMA_API_KEYS"),
    _resolve_strategy("OLLAMA"),
)

print(
    f" Epoxy starting — "
    f"Groq: {groq_pool.total_keys} keys ({groq_pool.strategy.value}), "
    f"Ollama: {ollama_pool.total_keys} keys ({ollama_pool.strategy.value})"
)


# ─────────────────────────────────────────────
# Hot-reload pools when .env changes on disk
# (e.g. edited via Pterodactyl File Manager)
# ─────────────────────────────────────────────

async def _reload_pools_if_env_changed(*, force: bool = False):
    global _last_env_mtime, groq_pool, ollama_pool, groq_client, ollama_client
    try:
        mtime = ENV_PATH.stat().st_mtime
    except OSError:
        return

    if not force and mtime <= _last_env_mtime:
        return

    async with _env_reload_lock:
        try:
            mtime = ENV_PATH.stat().st_mtime
            if mtime <= _last_env_mtime:
                return
            load_dotenv(ENV_PATH, override=True)
            new_groq = CredentialPool("groq", _parse_keys("GROQ_API_KEYS"), _resolve_strategy("GROQ"))
            new_ollama = CredentialPool("ollama", _parse_keys("OLLAMA_API_KEYS"), _resolve_strategy("OLLAMA"))
            groq_pool = new_groq
            ollama_pool = new_ollama
            groq_client = ProviderClient(groq_pool, "https://api.groq.com", "/openai/v1/chat/completions")
            ollama_client = ProviderClient(ollama_pool, "https://ollama.com", "/api/chat")
            _last_env_mtime = mtime
            print(f" Epoxy: reloaded pools from .env — Groq: {groq_pool.total_keys} keys, Ollama: {ollama_pool.total_keys} keys")
        except Exception as e:
            print(f" Epoxy: error reloading .env: {e}")


# ─────────────────────────────────────────────
# OpenAI ↔ Ollama Format Translation
# ─────────────────────────────────────────────

def transform_to_ollama_request(openai_body: dict) -> dict:
    model_name = openai_body.get("model", "deepseek-v3.1")
    if model_name.endswith("-cloud"):
        model_name = model_name[:-6]

    ollama_body = {
        "model": model_name,
        "messages": openai_body.get("messages", []),
        "stream": openai_body.get("stream", False),
    }

    options = {}
    if "temperature" in openai_body:
        options["temperature"] = openai_body["temperature"]
    if "top_p" in openai_body:
        options["top_p"] = openai_body["top_p"]
    if "max_tokens" in openai_body:
        options["num_predict"] = openai_body["max_tokens"]
    if "presence_penalty" in openai_body:
        options["presence_penalty"] = openai_body["presence_penalty"]
    if "frequency_penalty" in openai_body:
        options["frequency_penalty"] = openai_body["frequency_penalty"]
    if "stop" in openai_body:
        options["stop"] = openai_body["stop"]

    if options:
        ollama_body["options"] = options
    return ollama_body


def transform_from_ollama_response(ollama_resp: dict) -> dict:
    created_time = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created_time,
        "model": ollama_resp.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": ollama_resp.get("message", {}).get("role", "assistant"),
                    "content": ollama_resp.get("message", {}).get("content", ""),
                },
                "finish_reason": "stop" if ollama_resp.get("done") else None,
            }
        ],
        "usage": {
            "prompt_tokens": ollama_resp.get("prompt_eval_count", 0),
            "completion_tokens": ollama_resp.get("eval_count", 0),
            "total_tokens": (
                ollama_resp.get("prompt_eval_count", 0)
                + ollama_resp.get("eval_count", 0)
            ),
        },
    }


# ─────────────────────────────────────────────
# Streaming Generators
# ─────────────────────────────────────────────

async def ollama_stream_generator(client: httpx.AsyncClient, response: httpx.Response):
    created_time = int(time.time())
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    try:
        async for line in response.aiter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                done = chunk.get("done", False)
                model = chunk.get("model", "")

                openai_chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": "stop" if done else None,
                        }
                    ],
                }
                yield f"data: {json.dumps(openai_chunk)}\n\n"
            except Exception as e:
                print(f"Error parsing Ollama stream line: {e}")
        yield "data: [DONE]\n\n"
    finally:
        await response.aclose()
        await client.aclose()


async def groq_stream_generator(client: httpx.AsyncClient, response: httpx.Response):
    try:
        async for line in response.aiter_lines():
            if line:
                yield f"{line}\n"
    finally:
        await response.aclose()
        await client.aclose()


# ─────────────────────────────────────────────
# Provider Routing
# ─────────────────────────────────────────────

def get_provider(model_name: str) -> str:
    model_name_lower = model_name.lower()

    ollama_keywords = [
        "gpt-oss", "kimi-", "minimax-", "glm-", "qwen3",
        "cogito-", "deepseek-v4", "deepseek-v3",
    ]
    for kw in ollama_keywords:
        if kw in model_name_lower:
            return "ollama"

    groq_keywords = [
        "llama-3", "llama3", "mixtral", "gemma", "whisper", "deepseek-r1-distill",
    ]
    for kw in groq_keywords:
        if kw in model_name_lower:
            return "groq"

    if ":" in model_name or "cloud" in model_name_lower:
        return "ollama"

    if ollama_pool.total_keys > 0 and groq_pool.total_keys == 0:
        return "ollama"
    return "groq"


# ─────────────────────────────────────────────
# Provider HTTP Client Wrapper with Pool Rotation
# ─────────────────────────────────────────────

class ProviderClient:
    def __init__(self, pool: CredentialPool, base_url: str, api_path: str):
        self.pool = pool
        self.base_url = base_url
        self.api_path = api_path

    async def send_request(
        self, body: dict, headers: dict, stream: bool, is_ollama: bool = False
    ):
        max_retries = self.pool.total_keys * 2
        for attempt in range(max_retries):
            key = await self.pool.select()
            if key is None:
                raise HTTPException(
                    status_code=429,
                    detail=f"All {self.pool.name} keys exhausted or on cooldown.",
                )

            headers_snap = {**headers}
            if "Authorization" not in headers_snap:
                headers_snap["Authorization"] = f"Bearer {key.value}"
            elif "Bearer " in headers_snap.get("Authorization", ""):
                pass
            else:
                headers_snap["Authorization"] = f"Bearer {key.value}"

            client = httpx.AsyncClient()
            response = None
            try:
                if stream:
                    req = client.build_request(
                        "POST",
                        f"{self.base_url}{self.api_path}",
                        json=body,
                        headers=headers_snap,
                    )
                    response = await client.send(req, stream=True, timeout=60.0)

                    if response.status_code in (429, 402, 401):
                        status_code = response.status_code
                        await response.aclose()
                        await client.aclose()
                        await self.pool.mark_error(key, status_code)
                        if status_code == 429:
                            print(f" {self.pool.name} key rate limited (429). Rotating...")
                        elif status_code == 402:
                            print(f" {self.pool.name} key exhausted (402). Rotating...")
                        else:
                            print(f" {self.pool.name} key auth error (401). Rotating...")
                        await asyncio.sleep(0.5)
                        continue

                    response.raise_for_status()
                    await self.pool.mark_success(key)
                    return StreamingResponse(
                        ollama_stream_generator(client, response)
                        if is_ollama
                        else groq_stream_generator(client, response),
                        media_type="text/event-stream",
                    )
                else:
                    response = await client.post(
                        f"{self.base_url}{self.api_path}",
                        json=body,
                        headers=headers_snap,
                        timeout=60.0,
                    )

                    if response.status_code in (429, 402, 401):
                        status_code = response.status_code
                        await client.aclose()
                        await self.pool.mark_error(key, status_code)
                        if status_code == 429:
                            print(f" {self.pool.name} key rate limited (429). Rotating...")
                        elif status_code == 402:
                            print(f" {self.pool.name} key exhausted (402). Rotating...")
                        else:
                            print(f" {self.pool.name} key auth error (401). Rotating...")
                        await asyncio.sleep(0.5)
                        continue

                    response.raise_for_status()
                    await self.pool.mark_success(key)
                    data = response.json()
                    await client.aclose()
                    return transform_from_ollama_response(data) if is_ollama else data

            except httpx.HTTPStatusError as e:
                if response is not None:
                    await response.aclose()
                await client.aclose()

                status_code = e.response.status_code
                if status_code in (429, 402, 401):
                    await self.pool.mark_error(key, status_code)
                    print(f" {self.pool.name} HTTP error {status_code}. Rotating...")
                    continue
                raise HTTPException(status_code=status_code, detail=str(e))

            except Exception as e:
                if response is not None:
                    try:
                        await response.aclose()
                    except Exception:
                        pass
                await client.aclose()
                raise HTTPException(status_code=500, detail=str(e))

        raise HTTPException(
            status_code=429,
            detail=f"All {self.pool.name} keys exhausted after retries.",
        )


groq_client = ProviderClient(
    groq_pool,
    "https://api.groq.com",
    "/openai/v1/chat/completions",
)
ollama_client = ProviderClient(
    ollama_pool,
    "https://ollama.com",
    "/api/chat",
)


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(title="Hermes Free-Tier Proxy", version="1.1.0")


@app.on_event("startup")
async def startup():
    print(f" Epoxy: watching {ENV_PATH} for changes")

@app.post("/reload")
async def reload_pools():
    await _reload_pools_if_env_changed(force=True)
    return JSONResponse({
        "status": "ok",
        "providers": {
            "groq": groq_pool.get_status(),
            "ollama": ollama_pool.get_status(),
        },
    })

@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "providers": {
            "groq": groq_pool.get_status(),
            "ollama": ollama_pool.get_status(),
        },
    })


@app.get("/v1/models")
async def list_models():
    models = []
    if groq_pool.total_keys > 0:
        models.append({"id": "groq-llama-3.1-8b-instant", "object": "model", "created": int(time.time()), "owned_by": "groq"})
    if ollama_pool.total_keys > 0:
        models.append({"id": "ollama-deepseek-v3.1", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
    return JSONResponse({"object": "list", "data": models})


@app.get("/v1/capabilities")
async def capabilities():
    return JSONResponse({
        "object": "list",
        "platform": "hermes-free-pool",
        "auth": {"type": "bearer", "required": False},
        "features": {
            "chat_completions": True,
            "streaming": True,
        },
    })


@app.post("/v1/chat/completions")
async def handle_chat(request: Request):
    await _reload_pools_if_env_changed()
    body = await request.json()

    model_name = body.get("model", "")
    if not model_name:
        model_name = "deepseek-v3.1" if ollama_pool.total_keys > 0 else "llama-3.1-8b-instant"
        body["model"] = model_name

    provider = get_provider(model_name)
    stream = body.get("stream", False)

    if provider == "groq":
        if groq_pool.total_keys == 0:
            if ollama_pool.total_keys > 0:
                provider = "ollama"
            else:
                raise HTTPException(
                    status_code=503,
                    detail="No API keys configured for any provider.",
                )

    if provider == "ollama":
        if ollama_pool.total_keys == 0:
            if groq_pool.total_keys > 0:
                provider = "groq"
            else:
                raise HTTPException(
                    status_code=503,
                    detail="No API keys configured for any provider.",
                )

    if provider == "groq":
        ollama_body = body
        return await groq_client.send_request(ollama_body, {"Content-Type": "application/json"}, stream)
    else:
        ollama_body = transform_to_ollama_request(body)
        return await ollama_client.send_request(
            ollama_body,
            {"Content-Type": "application/json"},
            stream,
            is_ollama=True,
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "8080")))
    uvicorn.run(app, host="0.0.0.0", port=port)
