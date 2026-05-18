"""Reset the Docker integration stack without relying on bash paths."""

from __future__ import annotations

from integration_common import docker_compose, wait_for_postgres


def main() -> None:
    docker_compose("down", "--volumes", "--remove-orphans")
    docker_compose("up", "-d")
    wait_for_postgres()


if __name__ == "__main__":
    main()

