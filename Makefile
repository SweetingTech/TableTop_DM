.PHONY: setup up down up-local down-local migrate seed test ci ci-fast ci-integration rg1 rg1-local verify-docker verify-local verify install lint format typecheck unit contracts integration

setup:
	bash scripts/setup.sh

install:
	python -m pip install -r requirements-dev.txt
	python -c "import tomllib, pathlib, subprocess; data=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); deps=data.get('project', {}).get('dependencies', []); subprocess.check_call(['python','-m','pip','install',*deps]) if deps else None"

up:
	bash scripts/start.sh --mode docker

down:
	bash scripts/stop.sh --mode docker

up-local:
	bash scripts/start.sh --mode local

down-local:
	bash scripts/stop.sh --mode local

migrate:
	bash infra/scripts/migrate.sh

seed:
	bash infra/scripts/seed_demo.sh

lint:
	ruff check .

format:
	ruff format --check .

typecheck:
	mypy .

unit:
	pytest -m "unit"

contracts:
	pytest -m "contracts"

integration:
	pytest -m "integration"

rg1:
	bash scripts/rg1.sh --mode docker

rg1-local:
	bash scripts/rg1.sh --mode local

ci-fast: install lint format typecheck unit contracts

ci-integration:
	@mkdir -p burn-bag
	@if bash scripts/docker_runtime_available.sh; then \
		rm -f burn-bag/ci-integration-skipped.txt; \
		echo "[ci-integration] Docker runtime available; running integration tests"; \
		$(MAKE) up; \
		pytest -m "integration"; \
		$(MAKE) down; \
	else \
		echo "[ci-integration] SKIP: Docker runtime unavailable; integration tests skipped"; \
		echo "SKIPPED: docker runtime unavailable" > burn-bag/ci-integration-skipped.txt; \
	fi

ci: ci-fast ci-integration

test: ci

verify-docker:
	python3 scripts/audit_todo.py --full --strict --mode docker

verify-local:
	python3 scripts/audit_todo.py --full --strict --mode local

verify: verify-docker verify-local
