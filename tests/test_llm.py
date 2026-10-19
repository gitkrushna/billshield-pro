"""Transport safety and accounting tests use synthetic responses, never live calls."""

import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from billshield.llm import (
    DeepSeekLLM,
    LiveModelCallsDisabled,
    ModelDeadlineExceeded,
    ModelResponseError,
    ModelTransportError,
    TokenPrices,
)

PRICES = TokenPrices(
    Decimal("0.003"),
    Decimal("0.15"),
    Decimal("0.60"),
    "Official DeepSeek off-peak USD/1M; fixture time is explicitly supplied",
    False,
)


def answer(model="deepseek-flash", content='{"ok":true}', **overrides):
    data = {
        "model": model,
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1000,
            "prompt_cache_hit_tokens": 400,
            "prompt_cache_miss_tokens": 600,
            "completion_tokens": 200,
        },
    }
    return data | overrides


def adapter(handler, **kwargs):
    return DeepSeekLLM(
        "fixture-key-do-not-log", transport=httpx.MockTransport(handler), **kwargs
    )


def test_missing_credential_never_calls_transport():
    def forbidden(_):
        pytest.fail("Credentialless adapter sent a request")

    with pytest.raises(LiveModelCallsDisabled):
        DeepSeekLLM(transport=httpx.MockTransport(forbidden)).complete([])


def test_json_request_version_identity_and_decimal_cost():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=answer())

    result = adapter(handler, prices=PRICES).complete(
        [{"role": "user", "content": "facts"}]
    )
    payload = json.loads(requests[0].content)
    assert payload["model"] == "deepseek-flash"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert requests[0].url == "https://api.deepseek.com/chat/completions"
    assert result.expected_version == "DeepSeek-V4.1-Flash-1017"
    assert result.resolved_model is None
    audit = result.usage["_billshield"]
    assert audit["version_attested"] is False
    assert Decimal(audit["cost_usd"]) == Decimal("0.0002112")
    assert audit["cost_status"] == "priced_usage"
    assert result.usage["prompt_cache_hit_tokens"] == 400


def test_attested_version_is_separate_from_requested_alias():
    result = adapter(
        lambda _: httpx.Response(200, json=answer(model="DeepSeek-V4.1-Flash-1017"))
    ).complete([])
    assert result.requested_model == "deepseek-flash"
    assert result.resolved_model == "DeepSeek-V4.1-Flash-1017"


@pytest.mark.parametrize(
    "reported", ["DeepSeek-Flash", "another-alias", "deepseek-flash"]
)
def test_alias_like_provider_response_does_not_attest_version(reported):
    result = adapter(
        lambda _: httpx.Response(200, json=answer(model=reported))
    ).complete([])
    assert result.resolved_model is None
    assert result.usage["_billshield"]["version_attested"] is False


def test_transient_retry_does_not_invent_zero_cost(monkeypatch):
    async def no_delay(_):
        pass

    monkeypatch.setattr("billshield.llm.asyncio.sleep", no_delay)
    statuses = iter([503, 429, 200])
    result = adapter(
        lambda _: httpx.Response(next(statuses), json=answer()), prices=PRICES
    ).complete([])
    audit = result.usage["_billshield"]
    assert len(audit["attempts"]) == 3
    assert audit["cost_usd"] is None
    assert Decimal(audit["known_success_cost_usd"]) == Decimal("0.0002112")
    assert audit["cost_status"] == "unknown_retry_cost"


def test_only_two_retries_and_sanitized_errors(monkeypatch):
    async def no_delay(_):
        pass

    monkeypatch.setattr("billshield.llm.asyncio.sleep", no_delay)
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadError("fixture-key-do-not-log private recipe", request=request)

    with pytest.raises(ModelTransportError) as error:
        adapter(handler).complete([{"role": "user", "content": "private recipe"}])
    assert len(calls) == 3
    assert "private recipe" not in str(error.value)
    assert "fixture-key-do-not-log" not in str(error.value)


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 422])
def test_nontransient_status_never_retries_or_follows_redirects(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="secret response", headers={"Location": "https://bad.invalid"}
        )

    with pytest.raises(ModelTransportError) as error:
        adapter(handler).complete([])
    assert len(calls) == 1
    assert "secret response" not in str(error.value)


@pytest.mark.parametrize(
    "data",
    [
        answer(content="not-json"),
        answer(content="[]"),
        answer(choices=[{"message": {"content": "{}"}, "finish_reason": "length"}]),
        answer(usage=[]),
        {},
    ],
)
def test_bad_json_or_truncated_response_is_rejected_without_retry(data):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=data)

    with pytest.raises(ModelResponseError):
        adapter(handler).complete([])
    assert len(calls) == 1


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"prompt_tokens": 1000, "completion_tokens": 200},
        {"prompt_tokens": 1, "prompt_cache_hit_tokens": 10, "completion_tokens": 200},
        {
            "prompt_tokens": 1000,
            "prompt_cache_hit_tokens": True,
            "prompt_cache_miss_tokens": 999,
            "completion_tokens": 200,
        },
    ],
)
def test_incomplete_or_inconsistent_usage_is_unpriced(usage):
    result = adapter(
        lambda _: httpx.Response(200, json=answer(usage=usage)), prices=PRICES
    ).complete([])
    assert result.usage["_billshield"]["cost_usd"] is None


def test_cache_miss_can_be_derived_from_complete_prompt_accounting():
    data = answer()
    del data["usage"]["prompt_cache_miss_tokens"]
    result = adapter(lambda _: httpx.Response(200, json=data), prices=PRICES).complete(
        []
    )
    assert Decimal(result.usage["_billshield"]["cost_usd"]) == Decimal("0.0002112")


def test_global_deadline_is_shared_and_attempt_timeout_is_capped(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("billshield.llm.monotonic", lambda: clock[0])

    async def advance(seconds):
        clock[0] += seconds

    monkeypatch.setattr("billshield.llm.asyncio.sleep", advance)
    instance = DeepSeekLLM("fixture")
    timeouts = []

    async def request(_, timeout):
        timeouts.append(timeout)
        clock[0] += timeout
        raise TimeoutError

    monkeypatch.setattr(instance, "_request_once", request)
    with pytest.raises(ModelDeadlineExceeded):
        instance.complete([], deadline_monotonic=170)
    assert timeouts == [60, 9.75]
    assert clock[0] == 170


def test_expired_budget_sends_nothing():
    instance = adapter(lambda _: pytest.fail("Expired call sent a request"))
    with pytest.raises(ModelDeadlineExceeded):
        instance.complete([], remaining_seconds=0)


def test_async_total_timeout_cancels_a_slow_transport():
    cancelled = []

    async def slow(_):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
        return httpx.Response(200, json=answer())

    with pytest.raises(ModelDeadlineExceeded):
        adapter(slow).complete([], remaining_seconds=0.01)
    assert cancelled == [True]


def test_async_completions_run_concurrently_in_one_request_loop():
    active = 0
    maximum = 0

    async def handler(_):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json=answer())

    async def run():
        instance = adapter(handler)
        return await asyncio.gather(*(instance.acomplete([]) for _ in range(3)))

    assert len(asyncio.run(run())) == 3
    assert maximum == 3
    assert active == 0


def test_engine_cancellation_propagates_without_retrying():
    calls = []
    finished = []

    async def handler(request):
        calls.append(request)
        try:
            await asyncio.sleep(1)
        finally:
            finished.append(True)
        return httpx.Response(200, json=answer())

    async def run():
        task = asyncio.create_task(adapter(handler).acomplete([]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(calls) == 1
    assert finished == [True]


def test_sync_wrapper_rejects_use_in_active_event_loop():
    async def run():
        with pytest.raises(RuntimeError, match="acomplete"):
            adapter(lambda _: pytest.fail("Nested sync call sent a request")).complete(
                []
            )

    asyncio.run(run())
