# Character-boundary verification evidence

These are actual passing JUnit reports generated during the B remediation run, rather than
manually written test-result summaries. [The manifest](manifest.json) records commands, immutable
tested commits, case counts and SHA256 digests. It includes both original and committed report
digests; configured-string matches were redacted before copying, including one match in a test
name. No failure diagnostics, environment dumps, credentials, screenshots or traces are included.

| Report | Actual cases | Tested source |
| --- | ---: | --- |
| [Unit/contracts](unit.xml) | 499 | `3f4e548bb5cd8321928454fdb7af5ce629041a69` |
| [PostgreSQL/RLS/restart](durable.xml) | 33 | `3f4e548bb5cd8321928454fdb7af5ce629041a69` |
| [Chromium journeys](browser.xml) | 5 | `3f4e548bb5cd8321928454fdb7af5ce629041a69` |
| [Cross-layer forbidden-source flow](boundary-flow.xml) | 4 | Test-only follow-up identified in the manifest |

The browser lane used a ready isolated reference-mode Flask server and real Chromium. Dialogue
used a local fixture; no external model was contacted. The durable lane used a disposable
PostgreSQL database with the runtime role/RLS and Redis15. It did not alter the user's live data.
The final four cases were added after the first three reports; the follow-up changes tests only.
These reports do not claim that all cases ran together at a later commit. Exact-head GitHub CI,
integration review and native Orderly acceptance are separate gates.

The immutable `f9b6f8e0c419fb86e83c0e070a45e06004d98341` GitHub jobs also passed all four
gates. Actual log excerpts are retained for [quality](ci-quality.txt),
[PostgreSQL integration](ci-integration.txt), [Chromium](ci-browser.txt) and
[image/wheel verification](ci-image.txt). Each records the original job URL, commit, completion
time and full-log SHA256, plus the committed excerpt digest in the manifest. Excerpts preserve
actual matching log lines rather than substituting a narrative result; they are not full logs.

## Original B criteria and inspectable sources

- B1 purpose separation: [persona contracts](../../../persona/models.py),
  [compiler](../../../persona/compilation/compiler.py) and the purpose tests in `unit.xml`.
- B2 authored identity/card/body separation: [identity validation](../../../domains/tabletop/character_identity.py),
  [card history](../../../domains/tabletop/character_history.py),
  [bindings](../../../domains/tabletop/character_bindings.py),
  [portal records](../../../domains/tabletop/portal.py),
  [Player form](../../../frontend/src/features/player/PlayerDashboardPage.tsx) and
  [identity adapter](../../../frontend/src/features/player/characterIdentity.ts).
  The browser report includes actual identity and binding journeys.
- B3 trusted evidence assembly: [context](../../../cognition/context.py),
  [learned knowledge](../../../cognition/knowledge.py) and
  [scoped resolver](../../../domains/tabletop/character_context.py).
- B4 entrypoint/runner wiring: [HTTP composition](../../../kernel/api/app.py),
  [runner](../../../cognition/runner.py), [decision receipts](../../../cognition/character_decisions.py),
  [entrypoint unit cases](../../../tests/unit/kernel/test_cognition_character_entrypoint.py) and
  [durable entrypoint cases](../../../tests/integration/test_cognition_character_entrypoint.py).
- B5 retrieval/summary/provider boundary: [knowledge](../../../cognition/knowledge.py),
  [dialogue grounding](../../../cognition/dialogue_generation.py),
  [knowledge regressions](../../../tests/unit/cognition/test_character_knowledge.py) and
  [durable knowledge cases](../../../tests/integration/test_character_knowledge.py).
- B6 producer/finalizer audit: [non-sensory tags](../../../kernel/perception_contracts.py) and
  [event finalization](../../../kernel/event_factory.py) suppress physical evidence for operator
  records. Existing [clock](../../../domains/tabletop/world_time.py),
  [activity/weather](../../../domains/tabletop/activities/__init__.py),
  [population binding/lifecycle](../../../population/runtime.py),
  [routine](../../../population/routines.py) and [social obligation](../../../population/life.py)
  producers explicitly tag those records `operator`. Durable knowledge tests check that matching
  ledger records produce no character observations. Future revision/protection producers remain in
  their original unfinished campaign tasks; these reports do not claim those systems exist.
  The actual [gardener/weather unit regression](../../../tests/unit/tabletop/test_activities.py)
  executes operator activity/weather/clock commands and asserts that no physical grants are
  emitted, so the producer evidence also includes a nonempty command sequence.
- B7 hidden/abandoned evidence across layers: [context/memory cases](../../../tests/unit/cognition/test_character_context.py),
  [god/operator separation](../../../tests/unit/kernel/test_character_context_api.py),
  [generated-dialogue cases](../../../tests/unit/cognition/test_dialogue_generation.py) and
  [combined source-to-speech cases](../../../tests/unit/cognition/test_character_boundary_flow.py).
  The combined cases seed abandoned-branch, foreign-world, operator and masked facts plus forged
  memory summaries, then inspect the actual provider request and generated utterance. A masked
  event can remain a source reference while its hidden text remains excluded. Scope filtering
  does not erase stored memory or constitute full campaign rewind.

The original B1–B7 acceptance criteria remain unchanged. A passing report or merged slice does
not independently accept B, other checklist sections or any full-campaign milestone.
