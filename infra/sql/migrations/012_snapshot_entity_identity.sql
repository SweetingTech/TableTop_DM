-- Projection equality does not imply equality of frozen entity identity or secrets.
-- Preserve legacy snapshot rows, IDs, references, RLS and append-only protections.
ALTER TABLE sim.snapshots
  DROP CONSTRAINT snapshots_world_id_source_branch_id_through_event_seq_state_key,
  ADD CONSTRAINT snapshot_frozen_artifact_identity
    UNIQUE (world_id, source_branch_id, through_event_seq, state_hash, artifact_id);
