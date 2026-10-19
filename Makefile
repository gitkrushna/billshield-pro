.PHONY: setup check isolation web-check seed verify-seed local-init up down

setup:
	uv sync --project api --frozen
	cd web && pnpm install --frozen-lockfile

check:
	uv run --project api ruff check api/src tests scripts
	uv run --project api pytest

web-check:
	cd web && pnpm lint && pnpm typecheck && pnpm build && pnpm check:client-secrets

isolation:
	uv run --project api --env-file .env.local python -c "import os,pytest; os.environ['RUN_DB_INTEGRATION']='1'; raise SystemExit(pytest.main(['tests/test_isolation.py','-q']))"

seed:
	uv run --project api --env-file .env.local python scripts/seed.py

verify-seed:
	uv run --project api --env-file .env.local python scripts/verify_seed.py

local-init:
	node scripts/dev-init.mjs

up:
	docker compose --env-file .env.local up --build -d

down:
	docker compose --env-file .env.local down
