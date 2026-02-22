import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_demo_seed_contains_pc_and_npc_token_coordinates() -> None:
    seed_sql = Path("infra/sql/seed/001_demo_campaign.sql").read_text(encoding="utf-8")
    json_blobs = re.findall(r"'(?P<obj>\{[^']*\})'::jsonb", seed_sql)

    objects = []
    for blob in json_blobs:
        try:
            objects.append(json.loads(blob))
        except json.JSONDecodeError:
            continue

    fighter = next(o for o in objects if o.get("class") == "fighter" and o.get("level") == 3)
    ranger = next(o for o in objects if o.get("class") == "ranger" and o.get("level") == 3)
    skirmisher = next(o for o in objects if o.get("role") == "skirmisher" and o.get("xp") == 100)

    assert (fighter.get("x"), fighter.get("y")) == (5, 5)
    assert (ranger.get("x"), ranger.get("y")) == (7, 5)
    assert (skirmisher.get("x"), skirmisher.get("y")) == (6, 5)
