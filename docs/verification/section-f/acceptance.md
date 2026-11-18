# Autonomous character acceptance

[The Section F checklist](../../AUTONOMOUS_CAMPAIGN_CHECKLIST.md#f-autonomous-decisions-models-and-narration)
is exercised through typed commands, durable worker state, and committed event evidence.

| Criterion | Implementation and evidence |
| --- | --- |
| F1 | [PR #113](https://github.com/SweetingTech/TableTop_DM/pull/113) verifies recovery after an action is invalidated by a newer committed revision. Superseded attempts stay fenced across restart. |
| F2 | [PR #114](https://github.com/SweetingTech/TableTop_DM/pull/114) verifies that a wounded character reevaluates withdrawal and healing as separate physical steps, with private plan continuity across restart. |
| F3 | [PR #115](https://github.com/SweetingTech/TableTop_DM/pull/115) verifies grounded model selection for live advice and unattended controllers. Action references resolve to the same perceived bodies shown in the model input. |
| F4 | [PR #115](https://github.com/SweetingTech/TableTop_DM/pull/115) verifies bounded OpenAI-compatible transport, provider accounting, strict eligible-action validation, and deterministic fallback. |
| F5 | [PR #116](https://github.com/SweetingTech/TableTop_DM/pull/116) verifies that a reply waits for the body's masked observation and commits one typed speech event with the original cause and correlation after restart. |
| F6 | [PR #117](https://github.com/SweetingTech/TableTop_DM/pull/117) verifies three narration audiences, stable lineage, actor-scoped retrieval and revocation, and retention across restart. |
| F7 | [PR #118](https://github.com/SweetingTech/TableTop_DM/pull/118) verifies repeated ineffective attacks and witnessed speech chains. A fresh runner uses the committed movement history to offer an alternative after backtracking. |
| F8 | [Unattended cast test](../../../tests/integration/test_autonomous_cast.py) verifies the scenario below with working and unavailable dialogue providers. |

The scenario starts in a new world on isolated PostgreSQL. A wounded character withdraws from
a threat and then mends their own injuries. A courier hears a line from the gardener and sends
a grounded reply. Scheduled rain stops weeding after two seconds, and the gardener resumes at
the same progress when it clears. The character runner, world runner, and projector are actual
processes. After launch, the verification reads state and those processes submit every action
and clock tick.

The scenario reaches its authored twelve-second boundary with improved health, one committed
causal reply, and ten seconds of garden work. Both controllers exhaust their two-action budgets.
The tests run the scenario with an OpenAI-compatible response and with an HTTP 503 outage. In the
outage, the courier falls back to an ordinary in-world utterance after bounded provider attempts.
Both cases have four unique character decisions and twelve unique clock ticks. Restart preserves
the outcome and causes no additional actions or provider calls.

Use the [PostgreSQL integration setup](../../TESTING.md) and run the scenarios with:

```powershell
$env:TTDM_INTEGRATION = '1'
uv run pytest -m integration tests/integration/test_autonomous_cast.py -v
```
