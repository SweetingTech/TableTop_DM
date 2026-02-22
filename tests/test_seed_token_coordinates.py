from pathlib import Path


def test_demo_seed_contains_pc_and_npc_token_coordinates() -> None:
    seed_sql = Path("infra/sql/seed/001_demo_campaign.sql").read_text(encoding="utf-8")

    assert '"class":"fighter","level":3,"proficiencies":["swords","athletics"],"x":5,"y":5' in seed_sql
    assert '"class":"ranger","level":3,"proficiencies":["bows","survival"],"x":7,"y":5' in seed_sql
    assert '"role":"skirmisher","xp":100,"x":6,"y":5' in seed_sql
