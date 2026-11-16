# A2–A8 closeout verification

These files contain actual completed verification output for the reliable-human-play closeout.
[manifest.json](manifest.json) records commands, tested revisions, exit codes, timestamps where
locally observed, transformations and exact committed report hashes. They are evidence for review;
they do not independently mark Orderly Task 2 complete.

The current code, tests and production assets were tested at
`9d63d25bdfb9e6baf5afd1be134ad846bae995c7`. This report-only companion changes no executable files.
The local lanes passed: 596 Python unit/contracts, 65 frontend tests, lint/format/build, 143 typed
modules, a clean wheel/runtime asset check and the actual two-client PostgreSQL browser journey.
The browser result includes unknown-command guidance, no POST or draft loss, subsequent movement,
speech, attacks, cross-client position/health, six map tokens, viewpoint isolation, reconnect,
application restart and desktop/mobile checks.

The full 139-test durable result is retained from successful GitHub run
[43776322410](https://github.com/SweetingTech/TableTop_DM/actions/runs/43776322410)
at `d8899380bed2e03f6b9d987b59bac47e111e8cc4`. Its backend and integration tests are byte-identical
to the current code revision. This is earlier CI evidence, not a new local full-suite run.
The current PR's final CI results remain separate. No screenshot, trace, database dump, credential
or private gameplay data is committed here.

| Original criterion | Implementation and actual result |
| --- | --- |
| A2 recoverable roster/binding/grants | [roster finalization](../../../kernel/api/roster.py), [unit-of-work](../../../kernel/database.py), [durable regressions](../../../tests/integration/test_roster_recovery.py), [fast output](fast.log), [full durable output](ci-integration.log) |
| A3 removal/control semantics | [controller command](../../../domains/tabletop/entities/control.py), [runtime fencing](../../../kernel/control.py), [migration 013](../../../infra/sql/migrations/013_roster_controller_revocation.sql), [full durable output](ci-integration.log) |
| A4 refresh boundary/deduplication/scope | [server refresh boundary](../../../domains/tabletop/spatial/refresh.py), [HTTP composition](../../../kernel/api/app.py), [client refresh](../../../frontend/src/features/game-console/sceneRefresh.ts), [console](../../../frontend/src/features/game-console/GameConsolePage.tsx), [browser output](human-play.log) |
| A5 clients/reconnect/ordering | [scene polling](../../../frontend/src/features/game-console/useConsoleScene.ts), [frontend regressions in fast output](fast.log), [two-client browser result](human-play.junit.xml) |
| A6 world/zone map/all tokens | [presentation](../../../domains/tabletop/spatial/presentation.py), [coordinates](../../../frontend/src/features/game-console/mapPosition.ts), [six-token negative-coordinate browser journey](human-play.log) |
| A7 actionable failure states | [typed adapter/parser](../../../frontend/src/features/game-console/api.ts), [parser regressions](../../../frontend/src/test/GameCommandParser.test.ts), [no-write adapter regression](../../../frontend/src/test/GameSceneRefreshApi.test.ts), [retained draft/no POST browser result](human-play.log) |
| A8 actual integrated acceptance journey | [executed test](../../../tests/e2e/test_human_play_closeout.py), [complete stdout](human-play.log), [JUnit result](human-play.junit.xml) |

Reports replace local Windows path prefixes with `<workspace>` / `<temp>` and remove ANSI controls.
Publishing fails closed on credential/connection-URL patterns; no credential store is read to
prepare these reports. The wheel report retains its final 60 actual output lines. The CI report
retains the complete pytest session while removing runner prefixes and setup/environment output.
Original and transformed byte hashes are distinguished in the manifest.
