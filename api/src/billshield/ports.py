"""Small infrastructure contracts; no vendor imports in future engine code."""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    email: str


@dataclass(frozen=True)
class UploadLink:
    file_id: UUID
    url: str
    headers: Mapping[str, str]
    expires_in: int


@dataclass(frozen=True)
class ModelResult:
    content: str
    requested_model: str
    expected_version: str
    resolved_model: str | None
    usage: Mapping[str, Any] | None


class Auth(Protocol):
    def verify(self, token: str) -> Identity: ...


class Database(Protocol):
    def tenant(self, identity: Identity, org_id: UUID) -> AbstractContextManager[Any]: ...


class ObjectStorage(Protocol):
    def create_upload(self, scope: Any, size: int, content_type: str) -> UploadLink: ...
    def finalize(self, scope: Any, file_id: UUID) -> str: ...
    def download_link(self, scope: Any, file_id: UUID) -> str: ...


class Email(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> None: ...


class Jobs(Protocol):
    def enqueue(
        self,
        scope: Any,
        kind: str,
        payload: dict,
        idempotency_key: str | None = None,
    ) -> UUID: ...
    def claim(self, scope: Any, lease_seconds: int = 60) -> Mapping[str, Any] | None: ...
    def complete(self, scope: Any, job_id: UUID, lease_token: UUID) -> bool: ...


class LLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> ModelResult: ...
