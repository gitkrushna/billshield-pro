FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12.14-slim-bookworm
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && useradd --create-home app
USER app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "billshield.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
