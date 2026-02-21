.PHONY: up healthcheck verify-schema migrate seed-demo

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
