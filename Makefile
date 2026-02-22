.PHONY: install build start stop up down healthcheck verify-schema migrate seed-demo db-reset compose-smoke build-images \
	lint format typecheck test unit contracts integration ci-fast ci-integration ci gates

install:
	python -m pip install -r requirements-dev.txt
	python -c "import tomllib, pathlib, subprocess; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); deps=data.get('project', {}).get('dependencies', []); subprocess.check_call(['python','-m','pip','install',*deps]) if deps else None"

build:
	docker build -t tabletop-dm:local .

start:
	bash scripts/start.sh

stop:
	bash scripts/stop.sh

up:
	bash scripts/start.sh

down:
	bash scripts/stop.sh

healthcheck:
	./infra/scripts/phase1_healthcheck.sh

verify-schema:
	./infra/scripts/phase2_verify_schema.sh

migrate:
	./infra/scripts/migrate.sh

seed-demo:
	./infra/scripts/seed_demo.sh

db-reset:
	./infra/scripts/db_reset.sh

compose-smoke:
	./infra/scripts/compose_smoke.sh

build-images:
	docker compose -f infra/docker-compose.yml build

lint:
	ruff check .

format:
	ruff format --check .

typecheck:
	mypy .

test: unit contracts integration

unit:
	pytest -m "unit" \
		--cov=services/mechanics \
		--cov=services/spatial \
		--cov=services/domain/content_rating \
		--cov=services/domain/social \
		--cov=services/domain/divine \
		--cov=services/domain/karma \
		--cov-report=term-missing \
		--cov-report=xml \
		--cov-fail-under=50

contracts:
	pytest -m "contracts"

integration:
	pytest -m "integration"

ci-fast: install lint format typecheck unit contracts

ci-integration: migrate seed-demo
	pytest -m "integration"

ci: ci-fast ci-integration

gates: ci
