"""Single DeepSeek adapter, intentionally disabled until the M2 checkpoint is approved."""

import httpx

from billshield.ports import ModelResult


class LiveModelCallsDisabled(RuntimeError):
    pass


class DeepSeekLLM:
    requested_model = "deepseek-flash"
    expected_version = "DeepSeek-V4.1-Flash-1017"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def complete(self, messages: list[dict[str, str]]) -> ModelResult:
        # Deliberately no environment flag that can accidentally enable M1 live calls.
        raise LiveModelCallsDisabled("Live DeepSeek calls require M2 approval")

    def _request_after_m2_approval(self, messages: list[dict[str, str]]) -> ModelResult:
        """Transport implementation kept behind the unconditional M1 public-method gate."""
        if not self.api_key:
            raise ValueError("DeepSeek credential missing")
        with httpx.Client(timeout=60) as client:
            response = client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.requested_model, "messages": messages},
            )
            response.raise_for_status()
            data = response.json()
        # The response's `model` can be the requested alias. That is not version attestation.
        reported = data.get("model")
        resolved = reported if reported and reported != self.requested_model else None
        return ModelResult(
            data["choices"][0]["message"]["content"],
            self.requested_model,
            self.expected_version,
            resolved,
            data.get("usage"),
        )
