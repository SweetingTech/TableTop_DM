-- Remove a legacy manual marker inserted by 016_local_join_codes.sql.
-- Migration tracking is owned by the migration runner, so every tracked row
-- should correspond to an actual migration filename.

DELETE FROM infra_meta.schema_migrations
WHERE version = '016_local_join_codes';
