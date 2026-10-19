.DEFAULT_GOAL := help
.PHONY: help up down stop migrate revision check ci test run api reset-db

help:		## Show available commans
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up:			## Start Postgres and apply migrations
	docker compose up -d db
	uv run alembic upgrade head

stop:		## Stop containers (keeps data)
	docker compose stop

down:		## Remove containers (keeps data volume)
	docker compose down

migrate:    ## Apply pending migrations
	uv run alembic upgrade head

revision:   ## Create a migration: make revision m="add prices table"
	uv run alembic revision --autogenerate -m "$(m)"

check:      ## Lint, format, and type check (auto-fixes)
	uv run ruff check . --fix
	uv run ruff format .
	uv run mypy src tests

ci:         ## Run exactly what CI runs (no auto-fix)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests
	uv run pytest

test:       ## Run tests
	uv run pytest

run:        ## Run the API locally with auto-reload
	uv run uvicorn quant_dashboard.main:app --reload

api:        ## Run the full stack in containers
	docker compose up --build

reset-db:   ## Wipe the database volume and re-migrate (destructive)
	docker compose down -v
	docker compose up -d db
	@echo "Waiting for Postgres..."
	@until docker compose exec -T db pg_isready -U quant -d quant >/dev/null 2>&1; do sleep 1; done
	uv run alembic upgrade head