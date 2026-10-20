"""Finish MVP HTTP boundary. No private input is included in errors or logs."""

import json
import logging
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from billshield.auth import AuthenticationError, JWTAuth
from billshield.config import Settings
from billshield.db import AuthorizationError
from billshield.execution import CheckInProgress, CheckRateLimited, StaleLease
from billshield.finish import CheckNotFound, CheckRequest, FinishService, IdempotencyConflict
from billshield.ports import Identity

MAX_BODY_BYTES = 64 * 1024
logger = logging.getLogger("billshield.requests")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def error_response(request_id: str, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status,
    )


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = False

        async def tracked_send(message):
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"cache-control", b"no-store"),
                ]
            await send(message)

        async def reject_large():
            response = error_response(
                request_id, 413, "body_too_large", "Request body is too large."
            )
            await response(scope, receive, tracked_send)

        try:
            headers = dict(scope.get("headers", []))
            length = headers.get(b"content-length")
            if length is not None:
                try:
                    if int(length) > MAX_BODY_BYTES:
                        return await reject_large()
                except ValueError:
                    response = error_response(
                        request_id, 400, "invalid_request", "Invalid request."
                    )
                    return await response(scope, receive, tracked_send)
            # Bound chunked bodies too, before JSON parsing or model validation.
            chunks = []
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > MAX_BODY_BYTES:
                    return await reject_large()
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            buffered = b"".join(chunks)
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": buffered, "more_body": False}
                return await receive()

            await self.app(scope, bounded_receive, tracked_send)
        except Exception:
            if started:
                raise
            response = error_response(
                request_id, 500, "internal_error", "The request could not be completed."
            )
            await response(scope, receive, tracked_send)
        finally:
            # Even paths and queries may contain confidential input.
            logger.info(json.dumps({"request_id": request_id, "status": status}))


def public_auth_config(settings: Settings) -> dict:
    issuer = settings.auth_issuer.rstrip("/")
    parsed = urlsplit(issuer)
    if (
        not issuer.endswith("/auth/v1")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        )
    ):
        raise RuntimeError("Public authentication configuration unavailable")
    key = settings.auth_publishable_key
    if not key.startswith("sb_publishable_"):
        try:
            if jwt.decode(key, options={"verify_signature": False}).get("role") != "anon":
                raise ValueError("Not a public auth key")
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise RuntimeError("Public authentication configuration unavailable") from exc
    return {"auth_url": issuer.removesuffix("/auth/v1"), "auth_publishable_key": key}


def create_app(settings: Settings | None = None, *, service=None, auth=None) -> FastAPI:
    settings = settings or Settings()
    application = FastAPI(
        title="BillShield Finish MVP", docs_url=None, redoc_url=None, openapi_url=None
    )
    application.add_middleware(RequestBoundary)
    bearer = HTTPBearer(auto_error=False)

    @lru_cache(maxsize=1)
    def get_service():
        return service if service is not None else FinishService(settings)

    @lru_cache(maxsize=1)
    def get_auth():
        return (
            auth
            if auth is not None
            else JWTAuth(
                settings.auth_issuer,
                settings.auth_audience,
                jwks_url=settings.auth_jwks_url,
                userinfo_url=settings.auth_userinfo_url,
                publishable_key=settings.auth_publishable_key,
            )
        )

    def identity(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Identity:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise AuthenticationError()
        return get_auth().verify(credentials.credentials)

    def organization(who: Annotated[Identity, Depends(identity)]) -> UUID:
        return get_service().session(who)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Pydantic's error list includes raw input, potentially recipes/tokens.
        return error_response(
            request.state.request_id,
            422,
            "invalid_request",
            "The request contains invalid or missing fields.",
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request.state.request_id,
            exc.status_code,
            "not_found" if exc.status_code == 404 else "invalid_request",
            "Resource not found." if exc.status_code == 404 else "Invalid request.",
        )

    @application.exception_handler(AuthenticationError)
    async def unauthenticated(request: Request, exc: AuthenticationError):
        response = error_response(
            request.state.request_id, 401, "unauthenticated", "A verified sign-in is required."
        )
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @application.exception_handler(AuthorizationError)
    async def forbidden(request: Request, exc: AuthorizationError):
        return error_response(
            request.state.request_id, 403, "forbidden", "Access is not permitted."
        )

    @application.exception_handler(CheckNotFound)
    async def missing_check(request: Request, exc: CheckNotFound):
        return error_response(request.state.request_id, 404, "not_found", "Check not found.")

    @application.exception_handler(IdempotencyConflict)
    async def conflict(request: Request, exc: IdempotencyConflict):
        return error_response(
            request.state.request_id,
            409,
            "idempotency_conflict",
            "This idempotency key already belongs to a different request.",
        )

    @application.exception_handler(CheckInProgress)
    @application.exception_handler(StaleLease)
    async def in_progress(request: Request, exc: Exception):
        response = error_response(
            request.state.request_id,
            409,
            "check_in_progress",
            "Check processing is in progress; retry with the same key.",
        )
        response.headers["Retry-After"] = "5"
        return response

    @application.exception_handler(CheckRateLimited)
    async def rate_limited(request: Request, exc: CheckRateLimited):
        response = error_response(
            request.state.request_id,
            429,
            "check_rate_limited",
            "The hourly check allowance has been reached.",
        )
        response.headers["Retry-After"] = "3600"
        return response

    @application.get("/healthz", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    @application.get("/api/config")
    def config():
        return public_auth_config(settings)

    @application.post("/api/session")
    def session(
        who: Annotated[Identity, Depends(identity)],
        org_id: Annotated[UUID, Depends(organization)],
    ):
        return {"org_id": str(org_id), "email": who.email}

    @application.get("/api/checks")
    def list_checks(
        who: Annotated[Identity, Depends(identity)],
        org_id: Annotated[UUID, Depends(organization)],
    ):
        return {"checks": get_service().list_checks(who, org_id)}

    @application.post("/api/checks")
    async def create_check(
        body: CheckRequest,
        who: Annotated[Identity, Depends(identity)],
        org_id: Annotated[UUID, Depends(organization)],
        idempotency_key: Annotated[
            str, Header(min_length=1, max_length=200, pattern=r"^[\x21-\x7e]+$")
        ],
    ):
        check_id, report = await get_service().create_check(who, org_id, idempotency_key, body)
        return {"id": str(check_id), "report": report}

    @application.get("/api/checks/{check_id}")
    def get_check(
        check_id: UUID,
        who: Annotated[Identity, Depends(identity)],
        org_id: Annotated[UUID, Depends(organization)],
    ):
        return {"id": str(check_id), "report": get_service().get_check(who, org_id, check_id)}

    return application


app = create_app()
