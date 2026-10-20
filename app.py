"""Vercel FastAPI entrypoint; exported Next assets use its public CDN folder."""

import sys
from pathlib import Path

from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "api" / "src"))

from billshield.app import app


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(ROOT / "public" / "index.html")
