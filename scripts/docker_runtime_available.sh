#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "[docker-runtime] ERROR: docker CLI not found in PATH" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[docker-runtime] ERROR: docker compose plugin unavailable" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[docker-runtime] ERROR: docker daemon/runtime is not usable" >&2
  exit 1
fi

exit 0
