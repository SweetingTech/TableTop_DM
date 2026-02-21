import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contracts

ALLOWED_TAGS_PATH = Path("docs/registry/domain_tags.json")


def test_allowlist_is_unique_and_non_empty() -> None:
    payload = json.loads(ALLOWED_TAGS_PATH.read_text(encoding="utf-8"))
    tags = payload["allowed_tags"]
    assert tags
    assert len(tags) == len(set(tags))


def test_sample_engine_emissions_are_subset_of_allowlist() -> None:
    payload = json.loads(ALLOWED_TAGS_PATH.read_text(encoding="utf-8"))
    allowed_tags = set(payload["allowed_tags"])

    sample_emitted_tags = {
        "combat.attack",
        "combat.damage",
        "virtue.mercy",
        "faction.support",
        "divine.blessing",
    }

    assert sample_emitted_tags.issubset(allowed_tags)
