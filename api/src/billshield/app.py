import json
import logging
from uuid import uuid4

from fastapi import FastAPI, Request

app = FastAPI(title="BillShield M1 infrastructure", docs_url=None, redoc_url=None)
logger = logging.getLogger("billshield.requests")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


@app.middleware("http")
async def request_id(request: Request, call_next):
    correlation_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = correlation_id
    # Paths, bodies, headers and query strings can contain confidential values: do not log them.
    logger.info(json.dumps({"request_id": correlation_id, "status": response.status_code}))
    return response


@app.get("/healthz")
async def health():
    return {"status": "ok", "milestone": "M1", "engine_available": False}
