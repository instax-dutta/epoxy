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
