import os
import json
import time
import uuid
import asyncio
import random
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv
import httpx

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)
_last_env_mtime: float = ENV_PATH.stat().st_mtime if ENV_PATH.exists() else 0
_env_reload_lock = asyncio.Lock()

PROVIDER_NAMES = ["groq", "ollama", "mistral"]

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
            if time.monotonic() >= self.cooldown_until:
                self.mark_ok()
                return True
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
        self.cooldown_until = 0


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
            elif status_code in (402, 403):
                key.mark_exhausted()
            elif status_code == 401:
                key.mark_auth_error()

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


def _parse_keys(env_var: str) -> list[str]:
    raw = os.environ.get(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _resolve_strategy(name: str) -> PoolStrategy:
    raw = os.environ.get(f"{name}_POOL_STRATEGY", "round_robin").lower()
    try:
        return PoolStrategy(raw)
    except ValueError:
        return PoolStrategy.ROUND_ROBIN


groq_pool = CredentialPool("groq", _parse_keys("GROQ_API_KEYS"), _resolve_strategy("GROQ"))
ollama_pool = CredentialPool("ollama", _parse_keys("OLLAMA_API_KEYS"), _resolve_strategy("OLLAMA"))
mistral_pool = CredentialPool("mistral", _parse_keys("MISTRAL_API_KEYS"), _resolve_strategy("MISTRAL"))

print(
    f" Epoxy starting — "
    f"Groq: {groq_pool.total_keys} keys ({groq_pool.strategy.value}), "
    f"Ollama: {ollama_pool.total_keys} keys ({ollama_pool.strategy.value}), "
    f"Mistral: {mistral_pool.total_keys} keys ({mistral_pool.strategy.value})"
)


async def _reload_pools_if_env_changed(*, force: bool = False):
    global _last_env_mtime, groq_pool, ollama_pool, mistral_pool
    global groq_client, ollama_client, mistral_client
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
            groq_pool = CredentialPool("groq", _parse_keys("GROQ_API_KEYS"), _resolve_strategy("GROQ"))
            ollama_pool = CredentialPool("ollama", _parse_keys("OLLAMA_API_KEYS"), _resolve_strategy("OLLAMA"))
            mistral_pool = CredentialPool("mistral", _parse_keys("MISTRAL_API_KEYS"), _resolve_strategy("MISTRAL"))
            groq_client = ProviderClient(groq_pool, "https://api.groq.com", "/openai/v1/chat/completions")
            ollama_client = ProviderClient(ollama_pool, "https://api.ollama.com", "/v1/chat/completions")
            mistral_client = ProviderClient(mistral_pool, "https://api.mistral.ai", "/v1/chat/completions")
            _last_env_mtime = mtime
            print(f" Epoxy: reloaded pools — Groq: {groq_pool.total_keys}, Ollama: {ollama_pool.total_keys}, Mistral: {mistral_pool.total_keys}")
        except Exception as e:
            print(f" Epoxy: error reloading .env: {e}")


def transform_to_ollama_request(openai_body: dict) -> dict:
    model_name = openai_body.get("model", "deepseek-v4-flash")

    if model_name.startswith("ollama-"):
        model_name = model_name[len("ollama-"):]
    if model_name.endswith("-cloud"):
        model_name = model_name[:-len("-cloud")]

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
            "total_tokens": ollama_resp.get("prompt_eval_count", 0) + ollama_resp.get("eval_count", 0),
        },
    }


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


async def sse_passthrough_generator(client: httpx.AsyncClient, response: httpx.Response):
    try:
        async for line in response.aiter_lines():
            if line:
                yield f"{line}\n"
    finally:
        await response.aclose()
        await client.aclose()


def get_provider(model_name: str) -> str:
    model_name_lower = model_name.lower()

    if model_name_lower.startswith("ollama-"):
        return "ollama"

    mistral_keywords = ["mistral-", "codestral-", "open-mistral", "open-mixtral", "open-codestral"]
    for kw in mistral_keywords:
        if kw in model_name_lower:
            return "mistral"

    ollama_keywords = [
        "gpt-oss", "kimi-", "minimax-", "glm-", "qwen3", "cogito-", "nemotron-",
        "deepseek-v4", "deepseek-v3",
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

    available = [p for p in PROVIDER_NAMES if _parse_keys(f"{p.upper()}_API_KEYS")]
    if available:
        return available[0]
    return "groq"


class ProviderClient:
    def __init__(self, pool: CredentialPool, base_url: str, api_path: str):
        self.pool = pool
        self.base_url = base_url
        self.api_path = api_path

    @staticmethod
    def _log_error(provider_name: str, key_status: KeyStatus):
        msg = {
            KeyStatus.RATE_LIMITED: "key rate limited (429)",
            KeyStatus.EXHAUSTED: "key exhausted (402)",
            KeyStatus.AUTH_ERROR: "key auth error (401)",
        }.get(key_status, f"key error ({key_status})")
        print(f" {provider_name} {msg}. Rotating...")

    async def _try_key(
        self, body: dict, headers: dict, stream: bool, is_ollama: bool, key: PoolKey
    ) -> tuple:
        headers_snap = {**headers, "Authorization": f"Bearer {key.value}"}
        client = httpx.AsyncClient(follow_redirects=True)
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
            else:
                response = await client.post(
                    f"{self.base_url}{self.api_path}",
                    json=body,
                    headers=headers_snap,
                    timeout=60.0,
                )

            if response.status_code in (403, 429, 402, 401):
                status = response.status_code
                await response.aclose()
                await client.aclose()
                await self.pool.mark_error(key, status)
                return None, True

            response.raise_for_status()
            await self.pool.mark_success(key)

            if stream:
                gen = (
                    ollama_stream_generator(client, response)
                    if is_ollama
                    else sse_passthrough_generator(client, response)
                )
                return StreamingResponse(gen, media_type="text/event-stream"), False
            else:
                data = response.json()
                await client.aclose()
                result = transform_from_ollama_response(data) if is_ollama else data
                return result, False

        except httpx.HTTPStatusError as e:
            if response is not None:
                await response.aclose()
            await client.aclose()
            status = e.response.status_code
            if status in (429, 402, 401):
                await self.pool.mark_error(key, status)
                print(f" {self.pool.name} HTTP error {status}. Rotating...")
                return None, True
            raise HTTPException(status_code=status, detail=str(e))

        except Exception as e:
            if response is not None:
                try:
                    await response.aclose()
                except Exception:
                    logger.exception("Error closing response during cleanup")
            await client.aclose()
            raise HTTPException(status_code=500, detail=str(e))

    async def send_request(
        self, body: dict, headers: dict, stream: bool, is_ollama: bool = False
    ):
        max_retries = max(self.pool.total_keys * 2, 1)
        key = None
        for _ in range(max_retries):
            if key is None or key.status != KeyStatus.OK:
                key = await self.pool.select()
            if key is None:
                raise HTTPException(
                    status_code=429,
                    detail=f"All {self.pool.name} keys exhausted or on cooldown.",
                )

            result, should_retry = await self._try_key(body, headers, stream, is_ollama, key)
            if not should_retry:
                return result

            self._log_error(self.pool.name, key.status)
            if key.status != KeyStatus.OK:
                key = None
            await asyncio.sleep(0.5)

        raise HTTPException(
            status_code=429,
            detail=f"All {self.pool.name} keys exhausted after retries.",
        )


groq_client = ProviderClient(groq_pool, "https://api.groq.com", "/openai/v1/chat/completions")
ollama_client = ProviderClient(ollama_pool, "https://api.ollama.com", "/v1/chat/completions")
mistral_client = ProviderClient(mistral_pool, "https://api.mistral.ai", "/v1/chat/completions")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    print(f" Epoxy: watching {ENV_PATH} for changes")
    yield


app = FastAPI(title="Epoxy", version="1.2.1", lifespan=lifespan)


@app.post("/reload")
async def reload_pools():
    await _reload_pools_if_env_changed(force=True)
    return JSONResponse({
        "status": "ok",
        "providers": {p: globals()[f"{p}_pool"].get_status() for p in PROVIDER_NAMES},
    })


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "providers": {p: globals()[f"{p}_pool"].get_status() for p in PROVIDER_NAMES},
    })


@app.get("/v1/models")
async def list_models():
    models = []
    if groq_pool.total_keys > 0:
        models.append({"id": "groq-llama-3.1-8b-instant", "object": "model", "created": int(time.time()), "owned_by": "groq"})
        models.append({"id": "groq-llama-3.3-70b-versatile", "object": "model", "created": int(time.time()), "owned_by": "groq"})
        models.append({"id": "groq-gemma2-9b-it", "object": "model", "created": int(time.time()), "owned_by": "groq"})
        models.append({"id": "groq-deepseek-r1-distill-llama-70b", "object": "model", "created": int(time.time()), "owned_by": "groq"})
        models.append({"id": "groq-compound-beta", "object": "model", "created": int(time.time()), "owned_by": "groq"})
    if ollama_pool.total_keys > 0:
        models.append({"id": "ollama-deepseek-v4-flash:cloud", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
        models.append({"id": "ollama-minimax-m3:cloud", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
        models.append({"id": "ollama-minimax-m2.7:cloud", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
        models.append({"id": "ollama-glm-5.1:cloud", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
        models.append({"id": "ollama-nemotron-3-super:cloud", "object": "model", "created": int(time.time()), "owned_by": "ollama"})
    if mistral_pool.total_keys > 0:
        models.append({"id": "mistral-large-latest", "object": "model", "created": int(time.time()), "owned_by": "mistral"})
        models.append({"id": "mistral-small-latest", "object": "model", "created": int(time.time()), "owned_by": "mistral"})
        models.append({"id": "open-mistral-nemo", "object": "model", "created": int(time.time()), "owned_by": "mistral"})
    return JSONResponse({"object": "list", "data": models})


@app.get("/v1/capabilities")
async def capabilities():
    return JSONResponse({
        "object": "list",
        "platform": "epoxy",
        "auth": {"type": "bearer", "required": False},
        "features": {"chat_completions": True, "streaming": True},
    })


@app.post("/v1/chat/completions")
async def handle_chat(request: Request):
    await _reload_pools_if_env_changed()
    body = await request.json()

    model_name = body.get("model", "")
    if not model_name:
        available = [p for p in PROVIDER_NAMES if globals()[f"{p}_pool"].total_keys > 0]
        model_name = f"{available[0]}-default" if available else "groq-llama-3.1-8b-instant"
        body["model"] = model_name

    provider = get_provider(model_name)
    stream = body.get("stream", False)

    # fallback chain: if the routed provider has no keys, try others
    if globals()[f"{provider}_pool"].total_keys == 0:
        fallback = [p for p in PROVIDER_NAMES if globals()[f"{p}_pool"].total_keys > 0]
        if not fallback:
            raise HTTPException(status_code=503, detail="No API keys configured for any provider.")
        provider = fallback[0]

    if provider == "groq":
        return await groq_client.send_request(body, {"Content-Type": "application/json"}, stream)
    elif provider == "mistral":
        return await mistral_client.send_request(body, {"Content-Type": "application/json"}, stream)
    else:
        model = body.get("model", "")
        if model.startswith("ollama-"):
            body["model"] = model[len("ollama-"):]
        return await ollama_client.send_request(body, {"Content-Type": "application/json"}, stream)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "8080")))
    uvicorn.run(app, host="0.0.0.0", port=port)
