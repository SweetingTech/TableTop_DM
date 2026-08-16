#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="docker"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    *)
      echo "[rg1] Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

echo "[rg1] Running RG1 smoke in mode=$MODE"
pytest -m "integration" \
  tests/integration/test_rg1_session_load.py \
  tests/integration/test_rg1_player_join_session.py \
  tests/integration/test_rg1_demo_map_load.py \
  tests/integration/test_rg1_spawn_tokens_render.py
pytest tests/test_rg1_remaining_flow.py
