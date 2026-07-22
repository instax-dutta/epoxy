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
from urllib.parse import quote
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from dotenv import load_dotenv
import httpx

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)
try:
    _last_env_mtime = ENV_PATH.stat().st_mtime if ENV_PATH.exists() else 0.0
except OSError:
    _last_env_mtime = 0.0
_env_reload_lock = asyncio.Lock()

PROVIDER_NAMES = ["groq", "ollama", "mistral", "cerebras", "deepseek", "cloudflare", "google"]

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
        self.has_retried_429 = False
        self.cooldown_until = time.monotonic() + COOLDOWN_SECONDS[KeyStatus.EXHAUSTED]

    def mark_auth_error(self):
        self.status = KeyStatus.AUTH_ERROR
        self.has_retried_429 = False
        self.cooldown_until = 0

    @property
    def cloudflare_account_id(self) -> str | None:
        if ":" in self.value:
            account_id, _, _ = self.value.partition(":")
            return account_id
        return None

    @property
    def cloudflare_token(self) -> str:
        if ":" in self.value:
            _, _, token = self.value.partition(":")
            return token
        return self.value


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


def _build_state():
    groq_pool = CredentialPool("groq", _parse_keys("GROQ_API_KEYS"), _resolve_strategy("GROQ"))
    ollama_pool = CredentialPool("ollama", _parse_keys("OLLAMA_API_KEYS"), _resolve_strategy("OLLAMA"))
    mistral_pool = CredentialPool("mistral", _parse_keys("MISTRAL_API_KEYS"), _resolve_strategy("MISTRAL"))
    cerebras_pool = CredentialPool("cerebras", _parse_keys("CEREBRAS_API_KEYS"), _resolve_strategy("CEREBRAS"))
    deepseek_pool = CredentialPool("deepseek", _parse_keys("DEEPSEEK_API_KEYS"), _resolve_strategy("DEEPSEEK"))
    cloudflare_pool = CredentialPool("cloudflare", _parse_keys("CLOUDFLARE_API_KEYS"), _resolve_strategy("CLOUDFLARE"))
    google_pool = CredentialPool("google", _parse_keys("GOOGLE_API_KEYS"), _resolve_strategy("GOOGLE"))
    return {
        "pools": {
            "groq": groq_pool,
            "ollama": ollama_pool,
            "mistral": mistral_pool,
            "cerebras": cerebras_pool,
            "deepseek": deepseek_pool,
            "cloudflare": cloudflare_pool,
            "google": google_pool,
        },
        "clients": {
            "groq": ProviderClient(groq_pool, "https://api.groq.com", "/openai/v1/chat/completions"),
            "ollama": ProviderClient(ollama_pool, "https://ollama.com", "/api/chat"),
            "mistral": ProviderClient(mistral_pool, "https://api.mistral.ai", "/v1/chat/completions"),
            "cerebras": ProviderClient(cerebras_pool, "https://api.cerebras.ai", "/v1/chat/completions"),
            "deepseek": ProviderClient(deepseek_pool, "https://api.deepseek.com", "/v1/chat/completions"),
            "cloudflare": ProviderClient(cloudflare_pool, "https://api.cloudflare.com", "/client/v4/accounts/{account_id}/ai/v1/chat/completions"),
            "google": ProviderClient(google_pool, "https://generativelanguage.googleapis.com", "/v1beta/models/{model}:generateContent", is_google=True),
        },
    }


_provider_state: dict = {}

VALIDATION_ENDPOINTS = {
    "groq": ("https://api.groq.com", "/openai/v1/models", "GET", None),
    "ollama": ("https://ollama.com", "/api/chat", "POST", {"model": "nemotron-3-super:cloud", "messages": [{"role": "user", "content": "hi"}], "options": {"num_predict": 1}, "stream": False}),
    "mistral": ("https://api.mistral.ai", "/v1/models", "GET", None),
    "cerebras": ("https://api.cerebras.ai", "/v1/models", "GET", None),
    "deepseek": ("https://api.deepseek.com", "/v1/models", "GET", None),
    "cloudflare": ("https://api.cloudflare.com", "/client/v4/accounts/_dummy_/ai/v1/models", "GET", None),
    "google": ("https://generativelanguage.googleapis.com", "/v1beta/models", "GET", None),
}


async def _validate_key(provider: str, key: PoolKey) -> KeyStatus:
    base_url, api_path, method, body = VALIDATION_ENDPOINTS[provider]
    try:
        async with httpx.AsyncClient() as client:
            if provider == "google":
                headers = {"Content-Type": "application/json"}
                url = f"{base_url}{api_path}?key={key.value}"
            elif provider == "cloudflare":
                headers = {"Authorization": f"Bearer {key.cloudflare_token}", "Content-Type": "application/json"}
                account_path = api_path.replace("{account_id}", quote(key.cloudflare_account_id, safe=""))
                url = f"{base_url}{account_path}"
            else:
                headers = {"Authorization": f"Bearer {key.value}", "Content-Type": "application/json"}
                url = f"{base_url}{api_path}"

            if method == "GET":
                resp = await client.get(url, headers=headers, timeout=10.0)
            else:
                resp = await client.post(url, headers=headers, json=body, timeout=10.0)
            if resp.status_code == 401:
                return KeyStatus.AUTH_ERROR
            if resp.status_code in (402, 403):
                return KeyStatus.EXHAUSTED
            return KeyStatus.OK
    except Exception:
        return KeyStatus.OK


async def validate_pools(state: dict):
    pools = state["pools"]
    for name in PROVIDER_NAMES:
        pool = pools[name]
        if pool.total_keys == 0:
            continue
        for key in pool._keys:
            status = await _validate_key(name, key)
            if status == KeyStatus.AUTH_ERROR:
                key.status = KeyStatus.AUTH_ERROR
                key.cooldown_until = 0
                print(f" {name}: key ...{key.value[-6:]} auth error — removed from rotation")
            elif status == KeyStatus.EXHAUSTED:
                key.status = KeyStatus.EXHAUSTED
                key.cooldown_until = time.monotonic() + COOLDOWN_SECONDS[KeyStatus.EXHAUSTED]
                print(f" {name}: key ...{key.value[-6:]} exhausted — cooling down 24h")


async def _reload_pools_if_env_changed(*, force: bool = False):
    global _last_env_mtime, _provider_state
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
            new_state = _build_state()
            await validate_pools(new_state)
            _provider_state = new_state
            _last_env_mtime = mtime
            pools = _provider_state["pools"]
            parts = [f"{p}: {pools[p].healthy_keys}/{pools[p].total_keys}" for p in PROVIDER_NAMES]
            print(f" Epoxy: reloaded pools — {'; '.join(parts)}")
        except Exception as e:
            print(f" Epoxy: error reloading .env: {e}")


def transform_to_ollama_request(openai_body: dict) -> dict:
    model_name = openai_body.get("model", "nemotron-3-super:cloud")

    if model_name.startswith("ollama-"):
        model_name = model_name[len("ollama-"):]

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


def transform_to_google_request(openai_body: dict) -> dict:
    system_instruction = None
    contents = []
    for msg in openai_body.get("messages", []):
        if msg["role"] == "system":
            system_instruction = {"parts": [{"text": msg["content"]}]}
        elif msg["role"] == "user":
            if isinstance(msg.get("content"), list):
                parts = []
                for part in msg["content"]:
                    if part.get("type") == "text":
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:image"):
                            mime = url.split(";")[0].split(":")[1]
                            b64 = url.split(",")[1]
                            parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                        else:
                            parts.append({"text": f"[Image: {url}]"})
                contents.append({"role": "user", "parts": parts})
            else:
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "tool":
            contents.append({"role": "user", "parts": [{"text": f"Tool result: {msg['content']}"}]})

    body = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = system_instruction

    generation_config = {}
    if "temperature" in openai_body:
        generation_config["temperature"] = openai_body["temperature"]
    if "top_p" in openai_body:
        generation_config["topP"] = openai_body["top_p"]
    if "max_tokens" in openai_body:
        generation_config["maxOutputTokens"] = openai_body["max_tokens"]
    if "stop" in openai_body:
        generation_config["stopSequences"] = openai_body["stop"] if isinstance(openai_body["stop"], list) else [openai_body["stop"]]

    if generation_config:
        body["generationConfig"] = generation_config

    return body


def transform_from_google_response(google_resp: dict, model: str) -> dict:
    created_time = int(time.time())
    candidate = (google_resp.get("candidates") or [{}])[0]
    content = candidate.get("content", {})
    parts = content.get("parts", [{}])
    text = parts[0].get("text", "") if parts else ""
    usage = google_resp.get("usageMetadata", {})

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop" if candidate.get("finishReason") == "STOP" else None,
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    }


def transform_from_google_stream_chunk(chunk: dict, model: str, chat_id: str, created_time: int) -> dict:
    candidate = (chunk.get("candidates") or [{}])[0]
    content = candidate.get("content", {})
    parts = content.get("parts", [{}])
    text = parts[0].get("text", "") if parts else ""
    finish_reason = candidate.get("finishReason")
    usage = chunk.get("usageMetadata", {})

    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": text},
                "finish_reason": "stop" if finish_reason == "STOP" else None,
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        } if usage else None,
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
            except Exception:
                logger.exception("Error parsing Ollama stream line")
        yield "data: [DONE]\n\n"
    finally:
        await response.aclose()
        await client.aclose()


async def google_stream_generator(client: httpx.AsyncClient, response: httpx.Response, model: str):
    created_time = int(time.time())
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    try:
        async for line in response.aiter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break
                try:
                    chunk = json.loads(data)
                    openai_chunk = transform_from_google_stream_chunk(chunk, model, chat_id, created_time)
                    yield f"data: {json.dumps(openai_chunk)}\n\n"
                except json.JSONDecodeError:
                    continue
            else:
                try:
                    chunk = json.loads(line)
                    openai_chunk = transform_from_google_stream_chunk(chunk, model, chat_id, created_time)
                    yield f"data: {json.dumps(openai_chunk)}\n\n"
                except json.JSONDecodeError:
                    continue
    finally:
        await response.aclose()
        await client.aclose()


async def sse_passthrough_generator(client: httpx.AsyncClient, response: httpx.Response):
    try:
        async for line in response.aiter_lines():
            if not line:
                continue
            sep = "\n\n"
            yield f"{line}{sep}"
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

    cerebras_keywords = ["cerebras-"]
    for kw in cerebras_keywords:
        if kw in model_name_lower:
            return "cerebras"

    deepseek_keywords = ["deepseek-"]
    for kw in deepseek_keywords:
        if kw in model_name_lower:
            return "deepseek"

    cloudflare_keywords = ["cloudflare-"]
    for kw in cloudflare_keywords:
        if kw in model_name_lower:
            return "cloudflare"

    google_keywords = ["google-"]
    for kw in google_keywords:
        if kw in model_name_lower:
            return "google"

    ollama_keywords = [
        "gpt-oss", "kimi-", "minimax-", "glm-", "qwen3", "qwen3.5",
        "cogito-", "nemotron-", "deepseek-v4", "deepseek-v3", "gemma4",
    ]
    for kw in ollama_keywords:
        if kw in model_name_lower:
            return "ollama"

    groq_keywords = [
        "llama-3", "llama3", "mixtral", "gemma", "gemma2", "whisper",
        "deepseek-r1-distill", "compound",
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
    def __init__(self, pool: CredentialPool, base_url: str, api_path: str, is_google: bool = False):
        self.pool = pool
        self.base_url = base_url
        self.api_path = api_path
        self.is_google = is_google

    @staticmethod
    def _log_error(provider_name: str, key_status: KeyStatus):
        msg = {
            KeyStatus.RATE_LIMITED: "key rate limited (429)",
            KeyStatus.EXHAUSTED: "key exhausted (402)",
            KeyStatus.AUTH_ERROR: "key auth error (401)",
        }.get(key_status, f"key error ({key_status})")
        print(f" {provider_name} {msg}. Rotating...")

    def _build_url(self, key: PoolKey, model: str | None = None) -> str:
        if self.pool.name == "cloudflare":
            account_id = quote(key.cloudflare_account_id, safe="")
            path = self.api_path.replace("{account_id}", account_id)
            return f"{self.base_url}{path}"
        elif self.is_google and model:
            model_name = model[len("google-"):] if model.startswith("google-") else model
            return f"{self.base_url}/v1beta/models/{quote(model_name)}:generateContent?key={key.value}"
        return f"{self.base_url}{self.api_path}"

    def _build_stream_url(self, key: PoolKey, model: str | None = None) -> str:
        if self.is_google and model:
            model_name = model[len("google-"):] if model.startswith("google-") else model
            return f"{self.base_url}/v1beta/models/{quote(model_name)}:streamGenerateContent?alt=sse&key={key.value}"
        return self._build_url(key, model)

    async def _try_key(
        self, body: dict, headers: dict, stream: bool, is_ollama: bool, key: PoolKey
    ) -> tuple:
        headers_snap = {**headers}
        if self.is_google:
            headers_snap.pop("Authorization", None)
        elif self.pool.name == "cloudflare":
            headers_snap["Authorization"] = f"Bearer {key.cloudflare_token}"
        else:
            headers_snap["Authorization"] = f"Bearer {key.value}"

        client = httpx.AsyncClient()
        response = None
        model = body.get("model", "")

        try:
            url = self._build_stream_url(key, model) if stream else self._build_url(key, model)

            if stream:
                req = client.build_request("POST", url, json=body, headers=headers_snap)
                response = await client.send(req, stream=True, timeout=60.0)
            else:
                response = await client.post(url, json=body, headers=headers_snap, timeout=60.0)

            if response.status_code in (301, 302, 307, 308):
                location = response.headers.get("Location")
                if location:
                    print(f" {self.pool.name} redirecting to {location}")
                    await response.aclose()
                    if stream:
                        req = client.build_request("POST", location, json=body, headers=headers_snap)
                        response = await client.send(req, stream=True, timeout=60.0)
                    else:
                        response = await client.post(location, json=body, headers=headers_snap, timeout=60.0)

            if response.status_code in (403, 429, 402, 401):
                status = response.status_code
                print(f" {self.pool.name} key error: HTTP {status} from {response.url}")
                await response.aclose()
                await client.aclose()
                await self.pool.mark_error(key, status)
                return None, True

            response.raise_for_status()
            await self.pool.mark_success(key)

            if stream:
                if is_ollama:
                    gen = ollama_stream_generator(client, response)
                elif self.is_google:
                    gen = google_stream_generator(client, response, model)
                else:
                    gen = sse_passthrough_generator(client, response)
                return StreamingResponse(gen, media_type="text/event-stream"), False
            else:
                data = response.json()
                await client.aclose()
                if self.is_google:
                    result = transform_from_google_response(data, model)
                elif is_ollama:
                    result = transform_from_ollama_response(data)
                else:
                    result = data
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _provider_state
    _provider_state = _build_state()
    print(" Epoxy: validating API keys...")
    await validate_pools(_provider_state)
    pools = _provider_state["pools"]
    parts = [f"{p}: {pools[p].healthy_keys}/{pools[p].total_keys} ({pools[p].strategy.value})" for p in PROVIDER_NAMES]
    print(f" Epoxy (universal LLM proxy) starting — {'; '.join(parts)}")
    print(f" Epoxy: watching {ENV_PATH} for changes")
    yield


app = FastAPI(title="Epoxy", version="1.3.0", lifespan=lifespan)


@app.post("/reload")
async def reload_pools():
    await _reload_pools_if_env_changed(force=True)
    pools = _provider_state["pools"]
    return JSONResponse({
        "status": "ok",
        "providers": {p: pools[p].get_status() for p in PROVIDER_NAMES},
    })


@app.get("/", response_class=HTMLResponse)
async def root():
    pools = _provider_state["pools"]
    port = os.environ.get("SERVER_PORT", os.environ.get("PORT", "8080"))
    base = f"http://localhost:{port}"

    def badge_html(name, pool):
        healthy = pool.healthy_keys
        total = pool.total_keys
        cls = "badge-green" if healthy > 0 else "badge-red"
        return f'<span class="badge {cls}">{name} {healthy}/{total}</span>'

    badges = "".join(badge_html(p.capitalize(), pools[p]) for p in PROVIDER_NAMES if pools[p].total_keys > 0)

    models_html = ""
    if pools["groq"].total_keys > 0:
        models_html += "<h3>Groq</h3><ul>"
        for m in ["groq-llama-3.3-70b-versatile", "groq-llama-3.1-8b-instant", "groq-mixtral-8x7b-32768", "groq-gemma2-9b-it", "groq-deepseek-r1-distill-llama-70b", "groq-gemma-7b-it", "groq-llama-guard-3-8b", "groq-llama3-70b-8192", "groq-llama3-8b-8192", "groq-whisper-large-v3"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["ollama"].total_keys > 0:
        models_html += "<h3>Ollama Cloud</h3><ul>"
        for m in ["ollama-glm-5.2:cloud", "ollama-nemotron-3-super:cloud", "ollama-minimax-m3:cloud", "ollama-glm-5.1:cloud", "ollama-kimi-k2.6:cloud", "ollama-minimax-m2.7:cloud", "ollama-deepseek-v4-flash:cloud", "ollama-gpt-oss:120b-cloud", "ollama-gpt-oss:20b-cloud", "ollama-gemma4:cloud", "ollama-nemotron-3-ultra:cloud", "ollama-kimi-k2.7-code:cloud", "ollama-qwen3.5:cloud", "ollama-glm-5:cloud"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["mistral"].total_keys > 0:
        models_html += "<h3>Mistral</h3><ul>"
        for m in ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["cerebras"].total_keys > 0:
        models_html += "<h3>Cerebras</h3><ul>"
        for m in ["cerebras-gemma-4-31b", "cerebras-qwen3-235b"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["deepseek"].total_keys > 0:
        models_html += "<h3>DeepSeek</h3><ul>"
        for m in ["deepseek-chat", "deepseek-reasoner"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["cloudflare"].total_keys > 0:
        models_html += "<h3>Cloudflare</h3><ul>"
        for m in ["cloudflare-kimi-k2", "cloudflare-glm-4.7", "cloudflare-granite-4"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"
    if pools["google"].total_keys > 0:
        models_html += "<h3>Google AI Studio</h3><ul>"
        for m in ["google-gemini-2.5-flash", "google-gemini-2.5-pro", "google-gemma-4-31b"]:
            models_html += f"<li><code>{m}</code></li>"
        models_html += "</ul>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Epoxy</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0d1117; color:#c9d1d9; line-height:1.6; padding:2rem; }}
  a {{ color:#58a6ff; }}
  h1 {{ font-size:2rem; margin-bottom:.25rem; }}
  h2 {{ font-size:1.3rem; margin:2rem 0 .75rem; border-bottom:1px solid #30363d; padding-bottom:.4rem; }}
  h3 {{ font-size:1.1rem; margin:1rem 0 .5rem; color:#8b949e; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:.8rem; font-weight:600; }}
  .badge-green {{ background:#1b3d27; color:#3fb950; }}
  .badge-red {{ background:#3d1b1b; color:#f85149; }}
  .badge-yellow {{ background:#3d3a1b; color:#d29922; }}
  code {{ background:#161b22; padding:2px 6px; border-radius:4px; font-size:.9em; }}
  pre {{ background:#161b22; padding:1rem; border-radius:6px; overflow-x:auto; margin:.5rem 0; }}
  pre code {{ background:transparent; padding:0; }}
  ul {{ padding-left:1.5rem; margin:.5rem 0; }}
  li {{ margin:.3rem 0; }}
  .endpoints {{ display:flex; gap:.5rem; flex-wrap:wrap; margin:.5rem 0; }}
  .endpoints a {{ background:#161b22; border:1px solid #30363d; padding:.4rem .8rem; border-radius:6px; text-decoration:none; font-size:.9rem; }}
  .endpoints a:hover {{ border-color:#58a6ff; }}
  .container {{ max-width:900px; margin:0 auto; }}
</style>
</head>
<body>
<div class="container">
  <h1>Epoxy</h1>
  <p style="color:#8b949e;margin-bottom:.5rem;">Free-Tier LLM Key Rotation Proxy</p>

  <div class="endpoints">
    <a href="/health">/health</a>
    <a href="/v1/models">/v1/models</a>
    <a href="/v1/capabilities">/v1/capabilities</a>
    <a href="/docs">/docs</a>
    <a href="/reload">/reload</a>
  </div>

  <div style="display:flex;gap:.75rem;flex-wrap:wrap;margin:1rem 0;">
    {badges}
  </div>

  <h2>Quickstart</h2>
  <pre><code>curl {base}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{{
  "model": "groq-llama-3.1-8b-instant",
  "messages": [{{"role": "user", "content": "Hello!"}}],
  "stream": true
}}'</code></pre>

  <h2>Available Models</h2>
  {models_html}

  <h2>Coding Agent Setup</h2>

  <h3>OpenCode</h3>
  <p>Add to <code>~/.config/opencode/opencode.json</code>:</p>
  <pre><code>{{
  "provider": {{
    "epoxy": {{
      "name": "Epoxy",
      "npm": "@ai-sdk/openai-compatible",
      "options": {{"baseURL": "{base}/v1"}},
      "models": {{
        "groq-llama-3.1-8b-instant": {{"name": "Groq Llama 3.1 8B"}},
        "groq-llama-3.3-70b-versatile": {{"name": "Groq Llama 3.3 70B"}},
        "ollama-deepseek-v4-flash:cloud": {{"name": "Ollama DeepSeek V4 Flash"}}
      }}
    }}
  }}
}}</code></pre>
  <p>Run <code>/connect</code> and paste <em>any string</em> as the API key.</p>

  <h3>Kilo Code</h3>
  <p>In Settings → Providers → Add Provider → <strong>OpenAI Compatible</strong>:</p>
  <ul>
    <li><strong>Base URL:</strong> <code>{base}/v1</code></li>
    <li><strong>API Key:</strong> any string</li>
  </ul>

  <h3>Cline</h3>
  <p>In Settings → API Provider → <strong>OpenAI Compatible</strong>:</p>
  <ul>
    <li><strong>Base URL:</strong> <code>{base}/v1</code></li>
    <li><strong>API Key:</strong> any string</li>
    <li><strong>Model ID:</strong> <code>groq-llama-3.1-8b-instant</code></li>
  </ul>

  <h3>Claude Code</h3>
  <p>Claude Code uses the Anthropic API — run a translation proxy:</p>
  <pre><code>git clone https://github.com/shirayner/cc-proxy
# Set OPENAI_BASE_URL={base}/v1 in .env
python start_proxy.py

ANTHROPIC_BASE_URL=http://localhost:8082 ANTHROPIC_API_KEY=any-value claude</code></pre>

  <h2>Python SDK</h2>
  <pre><code>from openai import OpenAI
client = OpenAI(base_url="{base}/v1", api_key="any-string")
response = client.chat.completions.create(
    model="groq-llama-3.1-8b-instant",
    messages=[{{"role": "user", "content": "Hello!"}}]
)</code></pre>

  <p style="margin-top:2rem;color:#8b949e;font-size:.85rem;border-top:1px solid #30363d;padding-top:1rem;">
    Epoxy — <a href="https://github.com/instax-dutta/epoxy">GitHub</a>
  </p>
</div>
</body>
</html>"""


@app.get("/health")
async def health():
    pools = _provider_state["pools"]
    return JSONResponse({
        "status": "ok",
        "providers": {p: pools[p].get_status() for p in PROVIDER_NAMES},
    })


@app.get("/v1/models")
async def list_models():
    pools = _provider_state["pools"]
    models = []
    t = int(time.time())
    if pools["groq"].total_keys > 0:
        for m in ["groq-llama-3.3-70b-versatile", "groq-llama-3.1-8b-instant", "groq-mixtral-8x7b-32768", "groq-gemma2-9b-it", "groq-deepseek-r1-distill-llama-70b", "groq-gemma-7b-it", "groq-llama-guard-3-8b", "groq-llama3-70b-8192", "groq-llama3-8b-8192", "groq-whisper-large-v3"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "groq"})
    if pools["ollama"].total_keys > 0:
        for m in ["ollama-glm-5.2:cloud", "ollama-nemotron-3-super:cloud", "ollama-minimax-m3:cloud", "ollama-glm-5.1:cloud", "ollama-kimi-k2.6:cloud", "ollama-minimax-m2.7:cloud", "ollama-deepseek-v4-flash:cloud", "ollama-gpt-oss:120b-cloud", "ollama-gpt-oss:20b-cloud", "ollama-gemma4:cloud", "ollama-nemotron-3-ultra:cloud", "ollama-kimi-k2.7-code:cloud", "ollama-qwen3.5:cloud", "ollama-glm-5:cloud"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "ollama"})
    if pools["mistral"].total_keys > 0:
        for m in ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "mistral"})
    if pools["cerebras"].total_keys > 0:
        for m in ["cerebras-gemma-4-31b", "cerebras-qwen3-235b"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "cerebras"})
    if pools["deepseek"].total_keys > 0:
        for m in ["deepseek-chat", "deepseek-reasoner"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "deepseek"})
    if pools["cloudflare"].total_keys > 0:
        for m in ["cloudflare-kimi-k2", "cloudflare-glm-4.7", "cloudflare-granite-4"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "cloudflare"})
    if pools["google"].total_keys > 0:
        for m in ["google-gemini-2.5-flash", "google-gemini-2.5-pro", "google-gemma-4-31b"]:
            models.append({"id": m, "object": "model", "created": t, "owned_by": "google"})
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
    pools = _provider_state["pools"]
    clients = _provider_state["clients"]

    model_name = body.get("model", "")
    if not model_name:
        available = [p for p in PROVIDER_NAMES if pools[p].total_keys > 0]
        model_name = f"{available[0]}-default" if available else "groq-llama-3.1-8b-instant"
        body["model"] = model_name

    provider = get_provider(model_name)
    stream = body.get("stream", False)

    if pools[provider].total_keys == 0:
        fallback = [p for p in PROVIDER_NAMES if pools[p].total_keys > 0]
        if not fallback:
            raise HTTPException(status_code=503, detail="No API keys configured for any provider.")
        provider = fallback[0]

    if provider in ("groq", "cerebras", "deepseek"):
        model = body.get("model", "")
        for prefix in ("groq-", "cerebras-", "deepseek-"):
            if model.startswith(prefix):
                body["model"] = model[len(prefix):]
                break
        return await clients[provider].send_request(body, {"Content-Type": "application/json"}, stream)
    elif provider == "cloudflare":
        body.pop("model", None)
        return await clients["cloudflare"].send_request(body, {"Content-Type": "application/json"}, stream)
    elif provider == "google":
        google_body = transform_to_google_request(body)
        return await clients["google"].send_request(google_body, {"Content-Type": "application/json"}, stream)
    elif provider == "mistral":
        return await clients["mistral"].send_request(body, {"Content-Type": "application/json"}, stream)
    else:
        ollama_body = transform_to_ollama_request(body)
        return await clients["ollama"].send_request(ollama_body, {"Content-Type": "application/json"}, stream, is_ollama=True)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "8080")))
    uvicorn.run(app, host="0.0.0.0", port=port)
