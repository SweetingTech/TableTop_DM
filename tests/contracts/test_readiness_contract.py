from services.api.application import PROJECT_ROOT, _expected_migration_version


def test_expected_migration_version_tracks_latest_repo_migration():
    migrations = sorted((PROJECT_ROOT / "infra" / "sql" / "migrations").glob("*.sql"))

    assert migrations
    assert _expected_migration_version() == migrations[-1].name
