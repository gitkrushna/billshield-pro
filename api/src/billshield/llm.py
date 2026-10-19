"""DeepSeek JSON transport with bounded retries and an explicit cost audit trail."""

import asyncio
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Any

import httpx

from billshield.ports import ModelResult


class LiveModelCallsDisabled(RuntimeError):
    """No credential was configured; no request was sent."""


class ModelDeadlineExceeded(TimeoutError):
    pass


class ModelTransportError(RuntimeError):
    """Sanitized failure containing no prompt, key, or provider response body."""


class ModelResponseError(ModelTransportError):
    pass


@dataclass(frozen=True)
class TokenPrices:
    """Verified USD prices per million tokens, explicitly supplied by the caller.

    Basis can identify a conservative upper bound rather than an invoice. An
    explicit basis avoids guessing a time band or an exceptional holiday date.
    """

    cache_hit: Decimal
    cache_miss: Decimal
    output: Decimal
    basis: str
    estimate: bool = True

    def __post_init__(self):
        if not self.basis or any(
            not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0
            for rate in (self.cache_hit, self.cache_miss, self.output)
        ):
            raise ValueError("Verified finite Decimal prices and a price basis are required")


def _token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _cost(usage: dict[str, Any], prices: TokenPrices | None) -> str | None:
    if prices is None:
        return None
    hit = _token_count(usage.get("prompt_cache_hit_tokens"))
    miss = _token_count(usage.get("prompt_cache_miss_tokens"))
    prompt = _token_count(usage.get("prompt_tokens"))
    output = _token_count(usage.get("completion_tokens"))
    if hit is not None and miss is None and prompt is not None and prompt >= hit:
        miss = prompt - hit
    if hit is None or miss is None or output is None:
        return None
    if prompt is not None and prompt != hit + miss:
        return None
    total = hit * prices.cache_hit + miss * prices.cache_miss + output * prices.output
    return str(total / Decimal(1_000_000))


class DeepSeekLLM:
    requested_model = "deepseek-flash"
    expected_version = "DeepSeek-V4.1-Flash-1017"
    endpoint = "https://api.deepseek.com/chat/completions"
    transient_statuses = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(
        self,
        api_key: str = "",
        *,
        prices: TokenPrices | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_tokens: int = 4096,
    ):
        if not 1 <= max_tokens <= 16384:
            raise ValueError("Invalid response token limit")
        self._api_key = api_key
        self.prices = prices
        self._transport = transport
        self.max_tokens = max_tokens

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        deadline_monotonic: float | None = None,
        remaining_seconds: float | None = None,
    ) -> ModelResult:
        if not self._api_key:
            raise LiveModelCallsDisabled("DeepSeek credential is not configured")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.acomplete(
                    messages,
                    deadline_monotonic=deadline_monotonic,
                    remaining_seconds=remaining_seconds,
                )
            )
        raise RuntimeError("Use await DeepSeekLLM.acomplete inside an async request")

    async def acomplete(
        self,
        messages: list[dict[str, str]],
        *,
        deadline_monotonic: float | None = None,
        remaining_seconds: float | None = None,
    ) -> ModelResult:
        if not self._api_key:
            raise LiveModelCallsDisabled("DeepSeek credential is not configured")
        started = monotonic()
        deadline = started + 240
        if deadline_monotonic is not None:
            deadline = min(deadline, deadline_monotonic)
        if remaining_seconds is not None:
            deadline = min(deadline, started + max(0, remaining_seconds))
        attempts: list[dict[str, Any]] = []
        unknown_attempt_cost = False
        for number in range(1, 4):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ModelDeadlineExceeded("Model execution deadline exceeded")
            try:
                response = await self._request_once(messages, min(60, remaining))
            except (httpx.TransportError, TimeoutError):
                unknown_attempt_cost = True
                attempts.append({"attempt": number, "outcome": "transport_failure"})
                response = None
            if response is not None:
                if response.status_code == 200:
                    return self._result(response, attempts, number, unknown_attempt_cost)
                attempts.append(
                    {"attempt": number, "outcome": "http_failure", "status": response.status_code}
                )
                if response.status_code not in self.transient_statuses:
                    raise ModelTransportError(
                        f"DeepSeek request failed (HTTP {response.status_code})"
                    )
                unknown_attempt_cost = True
            if number == 3:
                raise ModelTransportError("DeepSeek transient retry limit reached")
            delay = 0.25 * (2 ** (number - 1))
            if deadline - monotonic() <= delay:
                raise ModelDeadlineExceeded("Model execution deadline exceeded")
            await asyncio.sleep(delay)
        raise AssertionError("Unreachable retry state")

    async def _request_once(self, messages: list[dict[str, str]], timeout: float) -> httpx.Response:
        # Wall-clock cap over connect/write/read together. Per-operation HTTPX
        # timeouts alone would allow an indefinitely trickling response.
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout, transport=self._transport, follow_redirects=False
            ) as client:
                return await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.requested_model,
                        "messages": [
                            {"role": "system", "content": "Return one JSON object."},
                            *messages,
                        ],
                        "response_format": {"type": "json_object"},
                        # Official Chat Completions API: thinking.type=disabled.
                        "thinking": {"type": "disabled"},
                        "max_tokens": self.max_tokens,
                    },
                )

    def _result(self, response, attempts, number, unknown_attempt_cost) -> ModelResult:
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") not in (None, "stop"):
                raise ValueError("Incomplete completion")
            if not isinstance(content, str) or not isinstance(json.loads(content), dict):
                raise ValueError("Expected a JSON object")
            usage = data.get("usage")
            if usage is not None and not isinstance(usage, dict):
                raise ValueError("Invalid usage")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelResponseError(
                "DeepSeek returned an invalid or incomplete JSON object"
            ) from None
        reported = data.get("model")
        resolved = (
            reported
            if isinstance(reported, str)
            and re.fullmatch(r"DeepSeek-V\d+(?:\.\d+)*-Flash-\d{4}", reported, re.IGNORECASE)
            else None
        )
        usage = dict(usage or {})
        cost = _cost(usage, self.prices)
        usage["_billshield"] = {
            "response_model": reported if isinstance(reported, str) else None,
            "version_attested": resolved is not None,
            "attempts": [*attempts, {"attempt": number, "outcome": "success"}],
            "cost_usd": cost if not unknown_attempt_cost else None,
            "known_success_cost_usd": cost,
            "cost_status": "unknown_retry_cost"
            if unknown_attempt_cost
            else (
                "unpriced_or_incomplete_usage"
                if cost is None
                else ("estimate" if self.prices.estimate else "priced_usage")
            ),
            "pricing_basis": self.prices.basis if self.prices else None,
        }
        return ModelResult(content, self.requested_model, self.expected_version, resolved, usage)
