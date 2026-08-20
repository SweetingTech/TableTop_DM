"""TableTop DM command line: one runtime for play, populations, and trials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _print(value: Any) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="tabletop-dm")
    commands = root.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the local simulation service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    commands.add_parser("worker", help="run the Redis experiment worker")

    scenario = commands.add_parser("scenario", help="run simulated-player onboarding")
    scenario.add_argument("--cohort-size", type=int, default=12)
    scenario.add_argument("--seeds", type=int, nargs="+", default=[101, 202, 303])
    scenario.add_argument("--include-trials", type=int, default=6)

    persona = commands.add_parser("persona", help="generate a reproducible persona")
    persona.add_argument("--seed", type=int, required=True)
    persona.add_argument("--fixed", default="{}", help="JSON object of fixed dimensions")

    population = commands.add_parser("population", help="generate a Parquet persona pool")
    population.add_argument("--size", type=int, default=1_000)
    population.add_argument("--seed", type=int, default=17)
    population.add_argument("--output", type=Path, required=True)

    commands.add_parser("doctor", help="inspect local contracts and invariants")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "serve":
        from kernel.api.app import app

        app.run(host=args.host, port=args.port, debug=False)
        return 0
    if args.command == "worker":
        from redis import Redis
        from rq import Queue, Worker

        connection = Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
        Worker([Queue("experiments", connection=connection)], connection=connection).work()
        return 0
    if args.command == "scenario":
        from experiments.onboarding import OnboardingExperiment

        _print(
            OnboardingExperiment().run_cohort(
                cohort_size=args.cohort_size,
                seeds=tuple(args.seeds),
                include_trials=args.include_trials,
            )
        )
        return 0
    if args.command == "persona":
        from persona.generation import PersonaGenerator
        from persona.registry import PersonaSchemaRegistry

        _print(
            PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(
                args.seed, json.loads(args.fixed)
            )
        )
        return 0
    if args.command == "population":
        from population import PopulationStore

        destination = PopulationStore(args.output).generate(args.size, args.seed)
        _print({"artifact": str(destination), "size": args.size, "seed": args.seed})
        return 0
    if args.command == "doctor":
        from kernel.application import SimulationApplication
        from persona.registry import PersonaSchemaRegistry

        simulation = SimulationApplication()
        simulation.bootstrap_demo()
        _print(
            {
                "kernel_contract": "2.0.0",
                "persona_dimensions": len(PersonaSchemaRegistry.load_default().dimensions),
                "command_contracts": simulation.bus.contracts(),
                "worlds": len(simulation.worlds),
                "status": "ready",
            }
        )
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
