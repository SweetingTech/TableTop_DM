.PHONY: up healthcheck verify-schema migrate seed-demo db-reset compose-smoke build-images \
	lint format typecheck test unit contracts integration ci-fast ci-integration ci gates

up:
	./infra/scripts/phase1_up.sh

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

ci-fast: lint format typecheck unit contracts

ci-integration: migrate seed-demo
	pytest -m "integration"

ci: ci-fast ci-integration

gates: ci
