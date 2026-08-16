"""Wait for integration dependencies to become ready."""

from __future__ import annotations

from integration_common import wait_for_postgres


def main() -> None:
    wait_for_postgres()


if __name__ == "__main__":
    main()
