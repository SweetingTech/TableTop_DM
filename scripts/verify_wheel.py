#!/usr/bin/env python3
"""Verify a wheel contains and can load every non-Python runtime asset."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED_MEMBERS = (
    "persona/schema/core/dimensions.yaml",
    "persona/schema/world/dimensions.yaml",
    "persona/schema/tabletop/dimensions.yaml",
    "persona/schema/accessibility/dimensions.yaml",
    "infra/sql/migrations/001_simulation_kernel.sql",
    "infra/sql/migrations/002_identity_and_tabletop_workspaces.sql",
    "infra/sql/migrations/003_spatial_epistemics.sql",
    "infra/sql/migrations/004_persona_purpose.sql",
    "infra/sql/migrations/005_character_history_and_bindings.sql",
    "infra/sql/migrations/006_character_proposal_receipts.sql",
    "infra/sql/migrations/007_controller_handoff_runner.sql",
    "infra/sql/migrations/008_player_behavior_evidence.sql",
    "infra/sql/migrations/009_speech_combat_evidence.sql",
    "infra/sql/migrations/010_tactical_choice_evidence.sql",
    "infra/sql/migrations/011_population_body_binding.sql",
    "infra/sql/migrations/012_snapshot_entity_identity.sql",
    "infra/sql/migrations/013_roster_controller_revocation.sql",
    "infra/sql/migrations/014_world_due_work.sql",
    "infra/sql/migrations/015_scoped_narration.sql",
    "infra/sql/migrations/016_decision_origins.sql",
    "infra/sql/migrations/017_speech_cadence_evidence.sql",
    "infra/sql/migrations/018_controller_presence.sql",
    "infra/sql/migrations/019_character_recap_boundaries.sql",
    "infra/sql/migrations/020_contextual_support_evidence.sql",
    "infra/sql/migrations/021_campaign_checkpoint_holds.sql",
    "infra/sql/migrations/022_campaign_checkpoints.sql",
    "static/v2/index.html",
)


def verify_contents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        missing = [member for member in REQUIRED_MEMBERS if member not in members]
        if missing:
            raise RuntimeError(f"wheel is missing runtime assets: {missing}")
        if not any(
            re.fullmatch(r"static/v2/assets/index-[A-Za-z0-9_-]+\.js", member) for member in members
        ):
            raise RuntimeError("wheel is missing the compiled SPA entry module")


def verify_extracted_runtime(wheel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="tabletop-dm-wheel-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(root)
        for key in (
            "DATABASE_URL",
            "REDIS_URL",
            "QDRANT_URL",
            "TTDM_OPERATOR_TOKEN",
        ):
            environment.pop(key, None)
        smoke = """
import re
from pathlib import Path
from infra.migrate import DEFAULT_MIGRATIONS_DIR, discover
from kernel.api.app import create_app
from persona.registry import PersonaSchemaRegistry

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(len(PersonaSchemaRegistry.load_default().dimensions) == 80,
        "wheel persona dimensions differ from the runtime contract")
require([item.version for item in discover(DEFAULT_MIGRATIONS_DIR)] == [
    "001_simulation_kernel.sql",
    "002_identity_and_tabletop_workspaces.sql",
    "003_spatial_epistemics.sql",
    "004_persona_purpose.sql",
    "005_character_history_and_bindings.sql",
    "006_character_proposal_receipts.sql",
    "007_controller_handoff_runner.sql",
    "008_player_behavior_evidence.sql",
    "009_speech_combat_evidence.sql",
    "010_tactical_choice_evidence.sql",
    "011_population_body_binding.sql",
    "012_snapshot_entity_identity.sql",
    "013_roster_controller_revocation.sql",
    "014_world_due_work.sql",
    "015_scoped_narration.sql",
    "016_decision_origins.sql",
    "017_speech_cadence_evidence.sql",
    "018_controller_presence.sql",
    "019_character_recap_boundaries.sql",
    "020_contextual_support_evidence.sql",
    "021_campaign_checkpoint_holds.sql",
    "022_campaign_checkpoints.sql",
], "wheel migration discovery differs from the runtime contract")
app = create_app(artifact_root=Path("artifacts"))
client = app.test_client()
index = client.get("/v2/game")
require(index.status_code == 200, "wheel SPA route failed")
entry = re.search(rb'src="(/static/v2/assets/index-[^"]+\\.js)"', index.data)
require(entry is not None, "wheel SPA entry module was not referenced")
asset = client.get(entry.group(1).decode())
require(asset.status_code == 200, "wheel SPA entry module failed")
require("javascript" in asset.content_type, "wheel SPA entry content type differs")
"""
        subprocess.run(
            [sys.executable, "-c", smoke],
            cwd=root,
            env=environment,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error(f"not a wheel file: {wheel}")
    verify_contents(wheel)
    verify_extracted_runtime(wheel)
    print(f"wheel runtime assets verified: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
