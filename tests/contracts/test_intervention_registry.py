import json
from pathlib import Path

import pytest

from shared.schemas.contracts import ACTION_REGISTRY

pytestmark = pytest.mark.contracts

REGISTRY_PATH = Path("docs/registry/intervention_registry.json")


def test_registry_matches_runtime_actions() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    documented_actions = set(registry["actions"].keys())
    runtime_actions = set(ACTION_REGISTRY.keys())
    assert documented_actions == runtime_actions


def test_registry_entries_have_required_fields() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    required_fields = {"params", "tool", "ap_cost", "visibility"}

    for action_type, entry in registry["actions"].items():
        assert required_fields.issubset(
            entry.keys()
        ), f"{action_type} missing required contract fields"
        assert (
            isinstance(entry["params"], list) and entry["params"]
        ), f"{action_type} must define params"
        assert (
            isinstance(entry["tool"], str) and entry["tool"]
        ), f"{action_type} must define tool"
        assert isinstance(
            entry["ap_cost"], int
        ), f"{action_type} must define integer ap_cost"
        assert (
            isinstance(entry["visibility"], str) and entry["visibility"]
        ), f"{action_type} must define visibility"
