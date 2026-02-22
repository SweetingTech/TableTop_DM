#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

pytest -m "integration" \
  tests/integration/test_rg1_session_load.py \
  tests/integration/test_rg1_player_join_session.py \
  tests/integration/test_rg1_demo_map_load.py \
  tests/integration/test_rg1_spawn_tokens_render.py

pytest tests/test_rg1_remaining_flow.py
