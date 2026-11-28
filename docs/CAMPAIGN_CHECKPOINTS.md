# Campaign checkpoint and revision contract

The [campaign checklist](AUTONOMOUS_CAMPAIGN_CHECKLIST.md#i-complete-checkpoints-timeline-revision-and-correction) uses this contract for complete checkpoints and timeline revision. The existing [2.1 snapshots](API_AND_WORKFLOWS.md#snapshots-and-trials) remain projection and entity snapshots used by replay and trials. This contract specifies the complete campaign format and the conditions for publishing or restoring one.

## Manifest and causal cut

A complete checkpoint binds one world and canonical timeline branch to a source continuation epoch. Its manifest identifies the capture request, format and schema versions, triggering command or schedule when present, canonical projection version and SHA-256, branch-local committed command ordinal, last included `sim.events.seq_id` and event ID, and world clock position. The command ordinal and the event sequence are distinct. The event sequence is global across the database and can have gaps. All event and outbox lookups use the selected world and branch.

The [durable capture API](API_AND_WORKFLOWS.md#campaign-checkpoint-capture) publishes this archive
from a ready hold. Table and artifact reads share one PostgreSQL transaction snapshot.

The manifest lists every component below. Each entry has a schema identifier, immutable content hash, and one of these dispositions:

- **Frozen** includes the canonical serialized state at the cut. The reader checks its hash and exact lineage before using it.
- **Pinned** identifies immutable source content by identifier and digest. The manifest is eligible for restore only while that exact dependency remains available. References to branch events carry the cut and the ordered source identity or digest.
- **Rebuild** names the builder version and complete pinned inputs for a derived component. Restore requires the same access semantics as the original source.
- **Absent** records why an optional component was unavailable at the cut. A missing required source, failed read, or inaccessible artifact fails the capture.

Hash canonical serialization in stable key and primary-key order. Bind each component digest and its disposition into the checkpoint identity. Preserve previously accepted format readers when a component schema changes. Public responses may return the checkpoint ID, boundary, operator label, capture state, and high-level completeness. Section bytes, private artifact locations, hidden source IDs, and restoration internals stay behind operator authority. Account credentials, session tokens, and current role grants are outside the checkpoint.

| Component | Source at the cut | Restore rule |
| --- | --- | --- |
| Canonical body and world state | `sim.branch_projections`, branch-scoped entity identity, authorized controller metadata and `secret_state`, versioned simulation settings | Freeze the projection and branch entity metadata together. Verify exact body coverage and referential integrity before publication. Global role and account authority is always current. |
| Physical evidence | Canonical events, frozen `sim.event_perceptions`, observation scope and visible source references | Pin the exact ordered prefix. Recreate retained same-branch witnesses and masked evidence from those grants. Current location is irrelevant to a historical witness. |
| Minds and relationships | `cognition.mind_states`, observations, beliefs and evidence, memories, relationships and changes | Freeze the subjective stores including separately authorized writes. Validate entity, run and source-event lineage. Replaying bodies alone is insufficient to reconstruct them. |
| Population | Branch-local lifecycle state, materialized people and lifecycle transitions, population definitions, pools, cohorts and generator artifacts | Freeze mutable person, cohort and lifecycle state. Pin source definitions and pools including generator versions and artifact hashes. Rebuild the branch mirror against the frozen population inputs. |
| Character bindings and decisions | Branch/run/body/card/mind bindings, immutable character card revisions, persona assignments and compiled versions, runtime and controller assignments, handoffs, private proposal receipts and policy evidence | Freeze scoped bindings, control modes and epochs, and the history needed to rebuild equivalent policy inputs. Pin versioned identity, policy, compiler, prompt, model and behavior provenance. Reconcile human controllers with current world grants on resume. |
| Activities and game time | Activity, routine, needs, status, quest and party projections, world clock, `sim.schedules` and logical `sim.world_due_work` | Preserve simulated time, remaining work, due intent, and all branch-local resources. Recreate fresh physical work leases after handoff. Wall-clock expiry and work-claim owners are transient. |
| Randomness | Run seeds, branch-local allocation ordinal, RNG contract version, committed decisions and results | Preserve existing outcomes on replay. Record the seed policy and independent new lineage for fresh execution after a correction. |
| Campaign story and pending tasks | Branch-owned quests, chosen approaches, rewards and escrow, authored story and agenda progress when installed, pending branch/run schedules | Bind the story plan version and freeze progression, references and logical pending work. Record explicit absence of an uninstalled story subsystem. Experiment jobs, account administration, and unrelated campaigns are outside the cut. |
| Narration and retrieval | Scoped narration and knowledge builder versions, source events and frozen observations | Rebuild authorized narration and search from the pinned facts and observations. Recreate any needed Redis and Qdrant indexes for the restored scope. |
| Artifact provenance | Exact manifests for published domain, rules, assets, population, persona and model/prompt inputs used by the retained state | Verify immutable IDs, versions and digests. Reject a missing or damaged dependency. Operator labels and retention metadata do not replace content identity. |

## Quiescence and capture

1. A typed request checks current world authority, active branch and expected continuation epoch. The source gate stops new physical commits, control changes, and scheduling on that lineage. Stale commands may replay an existing idempotent receipt if its current read authorization permits it. They cannot produce a new commit. An operator can inspect or cancel a stalled capture.
2. Drain projection work for events up to the fixed cut. Read pending or leased `sim.outbox` rows by joining their source events to the exact branch, and count unpublished rows through the cut. The projector may finish that bounded prefix while action writers are fenced. A failed or outstanding predecessor is a visible pending reason. Do not treat a worker signal or the maximum projected event ID as proof of complete delivery.
3. Recheck the epoch, projection hash and outbox closure while holding an exclusive branch mutation fence. The capture reader must see committed projection, entity metadata, subjective and operational rows under one transaction snapshot. In-flight work may finish before this snapshot or may be rejected, but cannot publish part of its output across the cut. The same fence must cover direct mind/relationship writes, control and binding changes, population writes, narration publication, and scheduled work publication. Check lock ordering before routing an existing writer through this fence.
4. Persist content and validate the artifact digest, then publish the manifest and any reference to it in one database transaction. A crash may leave an unreferenced immutable file. It cannot leave a published manifest with partially captured state. Retry of the same request returns its receipt. Scheduled, event-boundary, and operator-labeled captures use this same path.

The reference adapter applies the same causal checks under its synchronized state boundary. For PostgreSQL, a database-consistent snapshot alone cannot prove that a committed event reached every witness if the projector still owns an unpublished row. Capture success requires the drain check as well as the consistent read.

Reopening an archive verifies the event sequence, command ordinal, and event-time
perception records against the stored digest. The query stops at the recorded cut
even if that branch has advanced. Pinned file artifacts must still match their stored hashes.

By default every archive is retained. An operator may set a branch policy and explicitly
apply it to completed automatic checkpoints. The repository retains manual captures, pins
and active holds. It verifies the newest completed archives before retiring any older one.
An immutable retirement marker records the applied policy before file cleanup. The manifest
and capture receipt stay available for audit. Trial snapshots and ledgers use their own
retention rules.

Revision and restore must also retain their source checkpoint until the timeline and
all associated recovery work release it.

## Restore and revision

A durable world has one explicit active canonical continuation at epoch zero on creation.
The pointer references an append-only lineage entry. Each later epoch requires a checkpoint
from its immediate parent. The revision operation must also record a private correction
reason, operator, seed policy, model and rules versions, and the expected epoch. Historical
canonical branches and events remain available for audit. Evaluation trials keep independent
snapshot lineage and proposal authority.

A prepared plan binds a verified checkpoint to the active epoch and derives deterministic
successor branch and run IDs. A fresh seed is reproducible from the checkpoint and request.
The paused candidate preserves simulated time and remaps clock, quest and encounter run references.
The plan records a digest and archived versions. It protects its source from retention
until the operator cancels it or the revision takes ownership of that reference.

The knowledge reconstruction uses only the frozen mind rows and the verified physical
prefix. Event, observation, belief, evidence and memory identities are stable within the
successor branch. A reference outside the cut fails validation. Witness grants and perceived
content stay unchanged. Earlier event receipts remain on their original timeline.

Activation verifies the plan again while holding the source branch. It persists the
paused clock, archived physical and subjective state, current authorized body control,
retained human evidence, population sources, and a replay baseline. The registered activation
command records the checkpoint, source and target timeline, epoch, and restored digest. The
command, its private event and outbox row commit with the pointer switch. A materialization
failure rolls back all staged rows. The current hold can be retried after restart or released by
cancelling the plan.

Paused restored controllers each receive the successor run's execution actor and its standard
world-scoped grants. The original execution actor and archived decisions remain in the old
timeline's ledger.

Prepare and validate the new projection, entity identities, retained source lineage and subjective visibility before switching the active pointer. Restore branch-scoped identities using a consistent mapping for all dependent rows. Record origin references to the historical input while presenting only the restored observations to characters. Rebuild narration and retrieval from the retained prefix. Never borrow current memories or queue entries from the abandoned suffix.

The pointer switch, typed correction receipt, and initial scheduling state must commit together. A failed or interrupted revision leaves the previous timeline active. Resuming the same operation is idempotent. Workers and controllers holding an old branch, continuation epoch, control epoch or run cannot publish new outputs after the switch. New work starts only when the selected timeline and its restored data are ready. A restored checkpoint can stay paused without creating another active history.

Replaying retained deltas verifies what happened in an existing lineage. Fresh execution after a rewind can diverge and must record its own versioned decisions. Rewind before a death removes later effects from the active story, including death-dependent quests or funeral memories. A typed in-world resurrection changes the living body in the current lineage and retains witnesses' actual experience in that lineage. Both paths use authorized typed mutation and leave distinct causal records.

The end-to-end gate is a raid death with affected possessions, relationships and an opportunity. Verify a pre-death checkpoint, witness-scoped consequences in the old timeline, coherent resumed state after correction, exclusion of discarded funeral memories, and one active pointer after interrupting and retrying the operation. Test crossed world/branch access, concurrent worker publication, a retained old retry, dropped acknowledgements, cold restart and replay.
