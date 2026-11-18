# Section G supplemental verification

This evidence addresses G2, G4, G5, and G8 on the original Task 8 claim.
The checks exercise the runtime merged by PR #126 and documented by PR #127.

## G2. Profile versions and identity

The [durable profile test](../../../tests/integration/test_section_g_proof.py)
reads both scoped endpoints. The movement profile reports `movement-behavior-1.0.0`.
The contextual choice profile reports `speech-combat-behavior-1.4.0`. Each returns the
human player's actor ID, the character ID, and a content address that includes the schema
version. Replacing only the version causes the existing model validator to reject the payload.
Four comparable human examples supporting MEND produce four source events and confidence of
four sevenths.

## G4. Restart, provenance, and profile rebuild

The same test records four human choices, commits one stand-in action, and returns control to the
human. It reads both profiles through a fresh application and compares each rebuilt payload with
the corresponding post-handoff profile. The durable command and event join retains every human
and stand-in origin and its execution actor. The stand-in event has no human-choice row, and the
rebuilt profile cites exactly the four original human events. The
[trial and direction regression](../../../tests/integration/test_section_g_campaign.py)
verifies that the alternate timeline's accepted choice leaves the canonical profile unchanged.

## G5. Exclusive control at takeover

The [durable takeover race](../../../tests/integration/test_section_g_proof.py) blocks a human
command during epoch 1 while the stand-in owns action authority. Two concurrent requests to
take control from epoch 1 produce one successful response and one conflict. The transaction
records exactly one transition to human control at epoch 2. Concurrent submission of the old
stand-in proposal and the current human action produces one committed movement, attributed to
the human. The old executor receives an authorization denial.

## G8. Recap access and typed control requests

The [durable recap access case](../../../tests/integration/test_section_g_proof.py) verifies the
owner and scoped operator read the same single witnessed event. A different signed-in player
with a character in the same world, an anonymous caller, and the owner with the wrong run
receive an authorization error with no narration entries or source event ID.
The [actual Chromium console journey](../../../tests/e2e/test_controller_runner_isolated.py)
captures the client adapters' requests. **Let character act** sends a typed autonomous handoff
with the run, current epoch, step limit, and idempotency key. **Show character recap** sends the
scoped read for the same run. **Take control** sends a human handoff from the current timed-out
epoch with a separate idempotency key and receives the next human epoch.
The [in-progress action regression](../../../tests/integration/test_controller_runner.py)
verifies the original wait and receipt survive takeover and command retries.

## Executed checks

On 2026-11-18 the five selected cases passed against a disposable PostgreSQL instance
with migrations 001–020 applied. Pytest reported `5 passed in 54.17s`.

- `test_versioned_profiles_rebuild_without_learning_stand_in_actions`
- `test_atomic_takeover_allows_one_epoch_and_only_its_new_controller`
- `test_control_recap_enforces_current_world_body_and_run_authority`
- `test_recap_return_preserves_in_progress_action_once`
- `test_trial_and_typed_direction_never_train_canonical_player_profile`

Chromium ran `test_player_leaves_autonomy_acts_and_player_returns[chromium]` against the
built console and isolated application. Pytest reported `1 passed in 27.27s`.
