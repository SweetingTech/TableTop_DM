#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  exit 1
fi

exit 0
