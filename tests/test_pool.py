import time
import pytest
from server import CredentialPool, PoolKey, PoolStrategy, KeyStatus, COOLDOWN_SECONDS


def test_pool_key_initial_state():
    key = PoolKey(value="sk-test")
    assert key.value == "sk-test"
    assert key.status == KeyStatus.OK
    assert key.request_count == 0
    assert key.cooldown_until == 0
    assert key.has_retried_429 is False
    assert key.is_healthy is True


def test_pool_key_mark_rate_limited_then_cooldown():
    key = PoolKey(value="sk-test")
    key.has_retried_429 = True
    key.mark_rate_limited()
    assert key.status == KeyStatus.RATE_LIMITED
    assert key.is_healthy is False

    key.cooldown_until = time.monotonic() - 1
    assert key.is_healthy is True
    assert key.has_retried_429 is False
    assert key.status == KeyStatus.OK


def test_pool_key_mark_ok_resets_has_retried():
    key = PoolKey(value="sk-test")
    key.has_retried_429 = True
    key.mark_ok()
    assert key.has_retried_429 is False
    assert key.status == KeyStatus.OK


def test_pool_key_mark_exhausted():
    key = PoolKey(value="sk-test")
    key.mark_exhausted()
    assert key.status == KeyStatus.EXHAUSTED
    assert key.is_healthy is False

    key.cooldown_until = time.monotonic() - 1
    assert key.is_healthy is True


def test_pool_key_mark_auth_error():
    key = PoolKey(value="sk-test")
    key.mark_auth_error()
    assert key.status == KeyStatus.AUTH_ERROR
    assert key.is_healthy is False


def test_pool_key_cooldown_durations():
    key = PoolKey(value="sk-test")
    now = time.monotonic()

    key.has_retried_429 = True
    key.mark_rate_limited()
    assert key.cooldown_until >= now + COOLDOWN_SECONDS[KeyStatus.RATE_LIMITED] - 1

    key.mark_exhausted()
    assert key.cooldown_until >= now + COOLDOWN_SECONDS[KeyStatus.EXHAUSTED] - 1

    key.mark_auth_error()
    assert key.cooldown_until == 0
    assert key.status == KeyStatus.AUTH_ERROR
    assert key.is_healthy is False


@pytest.mark.asyncio
async def test_pool_select_returns_none_when_no_healthy_keys():
    pool = CredentialPool("test", ["sk-a", "sk-b"])
    for k in pool._keys:
        k.mark_exhausted()

    result = await pool.select()
    assert result is None


@pytest.mark.asyncio
async def test_pool_select_round_robin():
    pool = CredentialPool("test", ["sk-a", "sk-b", "sk-c"], PoolStrategy.ROUND_ROBIN)
    order = []
    for _ in range(6):
        k = await pool.select()
        order.append(k.value)

    assert order == ["sk-a", "sk-b", "sk-c", "sk-a", "sk-b", "sk-c"]


@pytest.mark.asyncio
async def test_pool_select_fill_first():
    pool = CredentialPool("test", ["sk-a", "sk-b", "sk-c"], PoolStrategy.FILL_FIRST)
    k1 = await pool.select()
    k2 = await pool.select()
    k3 = await pool.select()
    assert k1.value == "sk-a"
    assert k2.value == "sk-a"
    assert k3.value == "sk-a"


@pytest.mark.asyncio
async def test_pool_select_least_used():
    pool = CredentialPool("test", ["sk-a", "sk-b"], PoolStrategy.LEAST_USED)
    await pool.select()
    await pool.select()

    for k in pool._keys:
        k.request_count = 5 if k.value == "sk-a" else 0

    result = await pool.select()
    assert result.value == "sk-b"


@pytest.mark.asyncio
async def test_pool_select_random():
    pool = CredentialPool("test", ["sk-a", "sk-b", "sk-c"], PoolStrategy.RANDOM)
    results = set()
    for _ in range(100):
        k = await pool.select()
        results.add(k.value)
    assert results == {"sk-a", "sk-b", "sk-c"}


@pytest.mark.asyncio
async def test_pool_select_skips_cooldown_keys():
    pool = CredentialPool("test", ["sk-a", "sk-b"], PoolStrategy.FILL_FIRST)
    pool._keys[0].status = KeyStatus.RATE_LIMITED
    pool._keys[0].cooldown_until = time.monotonic() + 3600

    result = await pool.select()
    assert result.value == "sk-b"


@pytest.mark.asyncio
async def test_pool_select_increments_request_count():
    pool = CredentialPool("test", ["sk-a"], PoolStrategy.ROUND_ROBIN)
    await pool.select()
    await pool.select()
    assert pool._keys[0].request_count == 2


@pytest.mark.asyncio
async def test_pool_mark_error_429_first_then_rate_limit():
    pool = CredentialPool("test", ["sk-a"])
    key = pool._keys[0]

    # First 429: sets has_retried_429, key stays OK
    await pool.mark_error(key, 429)
    assert key.has_retried_429 is True
    assert key.status == KeyStatus.OK
    assert key.is_healthy is True

    # Second 429: marks rate_limited
    await pool.mark_error(key, 429)
    assert key.status == KeyStatus.RATE_LIMITED
    assert key.is_healthy is False


@pytest.mark.asyncio
async def test_pool_mark_error_402():
    pool = CredentialPool("test", ["sk-a"])
    key = pool._keys[0]
    await pool.mark_error(key, 402)
    assert key.status == KeyStatus.EXHAUSTED


@pytest.mark.asyncio
async def test_pool_mark_error_401():
    pool = CredentialPool("test", ["sk-a"])
    key = pool._keys[0]
    await pool.mark_error(key, 401)
    assert key.status == KeyStatus.AUTH_ERROR


@pytest.mark.asyncio
async def test_pool_mark_success_resets_key():
    pool = CredentialPool("test", ["sk-a"])
    key = pool._keys[0]
    key.has_retried_429 = True
    key.status = KeyStatus.RATE_LIMITED

    await pool.mark_success(key)
    assert key.status == KeyStatus.OK
    assert key.has_retried_429 is False
    assert key.cooldown_until == 0


@pytest.mark.asyncio
async def test_pool_get_status():
    pool = CredentialPool("test", ["sk-abc123def"], PoolStrategy.ROUND_ROBIN)
    status = pool.get_status()
    assert status["total"] == 1
    assert status["healthy"] == 1
    assert status["strategy"] == "round_robin"
    assert status["keys"][0]["label"] == "...123def"
    assert status["keys"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_pool_select_after_cooldown_has_retried_reset():
    pool = CredentialPool("test", ["sk-a"])
    key = pool._keys[0]
    key.has_retried_429 = True
    key.status = KeyStatus.RATE_LIMITED
    key.cooldown_until = time.monotonic() - 1

    result = await pool.select()
    assert result is key
    assert result.has_retried_429 is False
    assert result.status == KeyStatus.OK


def test_transform_to_ollama_request_strips_ollama_prefix():
    from server import transform_to_ollama_request
    body = {"model": "ollama-nemotron-3-super:cloud", "messages": [{"role": "user", "content": "hi"}], "stream": False}
    result = transform_to_ollama_request(body)
    assert result["model"] == "nemotron-3-super:cloud"
    assert result["messages"] == body["messages"]
    assert result["stream"] is False


def test_transform_to_ollama_request_maps_options():
    from server import transform_to_ollama_request
    body = {"model": "ollama-foo", "messages": [], "temperature": 0.7, "max_tokens": 200, "stream": True}
    result = transform_to_ollama_request(body)
    assert result["model"] == "foo"
    assert result["options"]["temperature"] == 0.7
    assert result["options"]["num_predict"] == 200


def test_transform_from_ollama_response():
    from server import transform_from_ollama_response
    ollama_resp = {
        "model": "nemotron-3-super:cloud",
        "message": {"role": "assistant", "content": "Hello!"},
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }
    result = transform_from_ollama_response(ollama_resp)
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["prompt_tokens"] == 10
    assert result["usage"]["completion_tokens"] == 20
    assert result["usage"]["total_tokens"] == 30


def test_has_retried_429_reset_on_exhausted():
    from server import PoolKey
    key = PoolKey(value="test")
    key.has_retried_429 = True
    key.mark_exhausted()
    assert key.has_retried_429 is False


def test_cloudflare_pool_key_extracts_account_id():
    from server import PoolKey
    key_with_acct = PoolKey(value="my-account-id:cf-api-token")
    assert key_with_acct.cloudflare_account_id == "my-account-id"
    assert key_with_acct.cloudflare_token == "cf-api-token"

    key_without_acct = PoolKey(value="plain-api-token")
    assert key_without_acct.cloudflare_account_id is None
    assert key_without_acct.cloudflare_token == "plain-api-token"


def test_transform_to_google_request_basic():
    from server import transform_to_google_request
    body = {
        "model": "google-gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": "Hello!"}
        ],
        "temperature": 0.5,
    }
    result = transform_to_google_request(body)
    assert result["contents"][0]["parts"][0]["text"] == "Hello!"
    assert result["generationConfig"]["temperature"] == 0.5


def test_transform_to_google_request_with_system():
    from server import transform_to_google_request
    body = {
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]
    }
    result = transform_to_google_request(body)
    assert result["systemInstruction"]["parts"][0]["text"] == "Be helpful."
    assert result["contents"][0]["parts"][0]["text"] == "Hi"


def test_transform_from_google_response():
    from server import transform_from_google_response
    google_resp = {
        "candidates": [{
            "content": {"parts": [{"text": "Hello!"}], "role": "model"},
            "finishReason": "STOP",
        }],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30},
    }
    result = transform_from_google_response(google_resp, "gemini-2.5-flash")
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["total_tokens"] == 30


def test_get_provider_routes_new_providers():
    from server import get_provider
    assert get_provider("cerebras-gemma-4-31b") == "cerebras"
    assert get_provider("deepseek-chat") == "deepseek"
    assert get_provider("cloudflare-kimi-k2") == "cloudflare"
    assert get_provider("google-gemini-2.5-flash") == "google"


def test_has_retried_429_reset_on_auth_error():
    from server import PoolKey
    key = PoolKey(value="test")
    key.has_retried_429 = True
    key.mark_auth_error()
    assert key.has_retried_429 is False


@pytest.mark.asyncio
async def test_sse_passthrough_yields_double_newline():
    from server import sse_passthrough_generator

    class FakeClient:
        async def aclose(self):
            pass

    class FakeResponse:
        lines = ["data: {\"foo\":\"bar\"}", "", "data: [DONE]"]

        async def aiter_lines(self):
            for line in self.lines:
                yield line

        async def aclose(self):
            pass

    gen = sse_passthrough_generator(FakeClient(), FakeResponse())
    chunks = [c async for c in gen]
    assert len(chunks) == 2
    assert chunks[0] == 'data: {"foo":"bar"}\n\n'
    assert chunks[1] == "data: [DONE]\n\n"


def test_build_state_creates_all_providers():
    from server import _build_state
    state = _build_state()
    assert "pools" in state
    assert "clients" in state
    for name in ("groq", "ollama", "mistral", "cerebras", "deepseek", "cloudflare", "google"):
        assert name in state["pools"]
        assert name in state["clients"]
