.PHONY: install up reset down purge status migrate lint format typecheck unit contracts \
	frontend integration e2e test ci

install:
	uv sync --frozen
	npm --prefix frontend ci

up:
	uv run python scripts/manage.py start

reset:
	uv run python scripts/manage.py start --reset

down:
	uv run python scripts/manage.py stop

purge:
	uv run python scripts/manage.py stop --volumes

status:
	uv run python scripts/manage.py status

migrate:
	uv run python infra/migrate.py

lint:
	uv run ruff check kernel persona cognition population experiments domains identity infra scripts tests main.py
	npm --prefix frontend run lint

format:
	uv run ruff format --check kernel persona cognition population experiments domains identity infra scripts tests main.py

typecheck:
	uv run mypy kernel persona cognition population experiments domains identity infra main.py

unit:
	uv run pytest -m unit

contracts:
	uv run pytest -m contracts

frontend:
	npm --prefix frontend run test
	npm --prefix frontend run build

integration:
	TTDM_INTEGRATION=1 uv run pytest -m integration

e2e:
	uv run pytest -m e2e tests/e2e -v

test: unit contracts

ci: lint format typecheck unit contracts frontend
