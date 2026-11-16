# Section C verification

These are actual completed execution results for the original seven action-authority criteria.
[manifest.json](manifest.json) records exact revisions, commands, results, transformations and
SHA-256 hashes of retained report bytes. This report-only companion changes no executable source.
It does not independently complete Orderly Task4 or any later campaign milestone.

Code revision: `328df7b52c9aadaf0b5c99de0edd77c851960d85`, proposed in
[PR106](https://github.com/SweetingTech/TableTop_DM/pull/106) on main
`e67fb613c52baebc68d3835ceda7c1cdbd0ca530`. Current local gates passed
708 Python tests and70 frontend tests, lint/format/build,151 typed modules and clean wheel assets.
The full158-test local durable lane ran against unchanged core
`1020d5f444128a73a7213ee30fee4d48bf905624`; later revisions add private-delta HTTP presentation
and a protected current capability read without changing canonical transactions or domain outcomes.
Five durable quest cases passed against the identical runtime immediately before commit, and the
two-client PostgreSQL browser journey ran at the committed code revision. The two isolated
quest/trade SPA journeys ran at prior `d76b610e82cadf0cac2703bf1c9bf4408e879c1f`, whose frontend
and reference action behavior are unchanged. Coverage includes
source-command provenance, restart, replay, late retries, movement/reward rollback, concurrent
reward workers, desktop/mobile quest/trade play and the two-client PostgreSQL human-play journey.
The [complete prior CI durable session](ci-integration.log) passed all158 cases in1632.78 seconds
at exact prior `d76b610e82cadf0cac2703bf1c9bf4408e879c1f`. This is CI evidence, not a second local
run or a passing claim for the newer159-case CI lane. The new separate-process grant test failed
before the fix at the private-delta assertion, then passed with the four existing quest cases:
current database grants, rather than the API's cached DM grant, now fence new and cached receipts.

| Original criterion | Source and actual execution evidence |
| --- | --- |
| C1 body/weapon/ability/condition/cost-derived attacks | [rules](../../../domains/tabletop/rules.py), [body configuration](../../../domains/tabletop/body_configuration.py), [combat](../../../domains/tabletop/combat/__init__.py), [derived-combat durable cases](../../../tests/integration/test_derived_combat.py), [fast](fast.log), [full durable](integration.log) |
| C2 versioned learned spells and resource eligibility | [fixed spell handling](../../../domains/tabletop/magic/tactical.py), [rule/runner durable cases](../../../tests/integration/test_action_rules.py), [fast](fast.log), [full durable](integration.log) |
| C3 shared-clock action and lifecycle mechanics | [action costs](../../../domains/tabletop/action_time.py), [initiative](../../../domains/tabletop/initiative.py), [timed effects](../../../domains/tabletop/effects.py), [defeat/death/recovery](../../../domains/tabletop/recovery.py), [rest](../../../domains/tabletop/rest.py), [clock](../../../domains/tabletop/world_time.py), [full durable](integration.log) |
| C4 per-action recorded seeds, retry-stable receipts and replay | [allocation](../../../kernel/randomness.py), [reference bus](../../../kernel/command_bus.py), [durable bus](../../../kernel/postgres_repository.py), [replay](../../../kernel/replay.py), [actual concurrency/restart cases](../../../tests/integration/test_action_randomness.py), [full durable](integration.log) |
| C5 canonical live sheet and authored-card separation | [live projection](../../../domains/tabletop/character_state.py), [card rules](../../../domains/tabletop/portal.py), [sheet](../../../frontend/src/features/player/CharacterStatePanel.tsx), [ownership cases](../../../tests/integration/test_character_resource_ownership.py), [full durable](integration.log), [browser](browser.log) |
| C6 authorized objectives, evidence, funded rewards and trade | [quest contracts](../../../domains/tabletop/quests/contracts.py), [settlement](../../../domains/tabletop/quests/__init__.py), [evidence](../../../domains/tabletop/quests/evidence.py), [offers](../../../domains/tabletop/economy/__init__.py), [private receipt projection](../../../domains/tabletop/receipts.py), [corrected durable](receipt-integration.log), [browser](browser.log) |
| C7 shared human/agent rules, no-write rejection, once-only spending and replay | [shared registration](../../../domains/tabletop/registry.py), [actual runner case](../../../tests/integration/test_action_rules.py), [trade parity](../../../tests/unit/kernel/test_trade_offers_api.py), [quest parity](../../../tests/unit/kernel/test_quest_evidence_api.py), [fast](fast.log), [full durable](integration.log), [corrected durable](receipt-integration.log) |

One attempted parallel narrow database lane failed at shared PostgreSQL role setup before tests;
that attempt is not a passing test result. Durable lanes were then serialized. CI at the exact
code head is [the kernel run](https://github.com/SweetingTech/TableTop_DM/actions/runs/43829210884)
and [the browser run](https://github.com/SweetingTech/TableTop_DM/actions/runs/43829210796); check
their current status separately. No model/provider availability or autonomous quest planning is
inferred from this mechanical enforcement evidence. Original section F remains responsible for
goal selection and pursuit, and every remaining original task retains its own acceptance gate.

Reports remove ANSI controls, normalize terminal blank lines and replace local path prefixes. Publication fails closed on
credential/connection patterns without reading a credential store. The wheel report retains its
actual final60 lines. Original versus retained byte hashes are explicit in the manifest.
