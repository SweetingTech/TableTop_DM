# Section G acceptance evidence

The production code and compiled console come from `a59f133483e4fe9fcd9707dea7ef04789ae493e7`
([PR #126](https://github.com/SweetingTech/TableTop_DM/pull/126)). The final two proof cases
ran from `a2a72e8f2689ca0eda0547d3ea253f118f66ace9`. That revision adds test assertions
and uses the same production code and compiled console.

## G1. A durable human choice contains only the character's known options

[The PostgreSQL regression](../../../tests/integration/test_section_g_proof.py)
creates a visible opponent and an invisible opponent through the entity API. Both attack the
player's character. The invisible attack commits an event with its attacker's ID, while the
character's durable observation linked to that same event reads “Sounds of nearby fighting.”
The authenticated player attacks the visible opponent. The test joins the resulting event
receipt to the human-choice row, its accepted command, and the exact world, branch, run,
character, and body binding.

The accepted command records `HUMAN_INPUT` and human authorship. The persisted choice's frame
records the revision immediately before the resulting command, and its known threat and selected
attack point to the visible opponent. The selected attack is among the stored options. The
invisible opponent's ID, name, and synthetic private motive are absent from the entire stored
choice. The case passed on disposable PostgreSQL 16.

## G6. The player can see how campaign pause affects autonomy

[The Chromium player journey](../../../tests/e2e/test_controller_runner_isolated.py) opens the
compiled console as its signed-in player. It asserts the visible text “A paused world stops
autonomous actions” before handoff, on the mobile layout, and after reconnect. The journey also
verifies the disconnect setting, a bounded autonomous turn, the returning character's recap,
and the takeover request. The case passed in Chromium.

Two [durable campaign pause cases](../../../tests/integration/test_world_time.py) verify that
pausing the world fences a prepared autonomous action at durable commit, and that a real
character runner can resume after the world is resumed without another handoff. Both passed
on disposable PostgreSQL 16.

## Evidence for the full checklist

| Criterion | Runtime evidence |
| --- | --- |
| G1 | The PostgreSQL regression above checks durable choice, authorship, perceptual scope, and the committed outcome. The [canonical and trial decision tests](../../../tests/integration/test_section_g_campaign.py) also distinguish director actions and trial inputs from canonical human choices. |
| G2 | [The profile and rebuild regression](../../../tests/integration/test_section_g_proof.py) checks movement and choice profile versions, persisted source event IDs and confidence, and content hashes. [The durable tactical choices](../../../tests/integration/test_tactical_choices.py) compare genuine offered alternatives and follow prior human choices. |
| G3 | [The choice policy tests](../../../tests/unit/kernel/test_speech_combat_behavior.py) show authored differences driving no-history actions. [The tactical fallback tests](../../../tests/unit/kernel/test_tactical_choices.py) preserve persona behavior for unavailable or unsupported examples and compare actually offered options. |
| G4 | [The profile rebuild regression](../../../tests/integration/test_section_g_proof.py) reopens the app and compares exact rebuilt profiles. Stored command, event, and evidence links preserve the original human inputs and exclude the stand-in. [Trial and direction isolation](../../../tests/integration/test_section_g_campaign.py) checks canonical profiles after both kinds of input. |
| G5 | [The atomic takeover race](../../../tests/integration/test_section_g_proof.py) commits one epoch change and one human movement. The previous stand-in's competing proposal is denied. [The controller integration suite](../../../tests/integration/test_controller_runner.py) also exercises concurrent runner commits. |
| G6 | The pause disclosure, disconnect, bound turn, reconnect, and explicit takeover pass through the compiled console journey above. The durable controller and pause tests exercise the corresponding server behavior. |
| G7 | [The mixed campaign integration](../../../tests/integration/test_section_g_campaign.py) joins the accepted canonical command to its event and private decision receipt. It identifies the dedicated action executor separately from the human whose choices supplied the profile. |
| G8 | [The durable recap access regression](../../../tests/integration/test_section_g_proof.py) permits the owner and scoped operator and denies wrong run, unrelated player, and anonymous access. The compiled console journey captures real typed handoff, recap, and return requests. [The existing controller cases](../../../tests/integration/test_controller_runner.py) also preserve an in-progress action and its original receipt. |
| G9 | [The mixed campaign integration](../../../tests/integration/test_section_g_campaign.py) runs solo, mixed, and fully autonomous modes in the same campaign, with a real durable projector and runner. The previously played character follows learned behavior and the companion without history uses its authored backstory. |

The [original verification](acceptance.md), [recorded commands and results](checks.txt),
and [supplemental verification](four-criteria.md) preserve the earlier results. The exact
hosted baseline ran
[190 PostgreSQL cases](https://github.com/SweetingTech/TableTop_DM/actions/runs/44310001317/job/134821368571)
and [49 Chromium cases](https://github.com/SweetingTech/TableTop_DM/actions/runs/44310001247/job/134821367024).
The supplemental revision ran
[193 PostgreSQL cases](https://github.com/SweetingTech/TableTop_DM/actions/runs/44341566286/job/134932649699)
and [49 Chromium cases](https://github.com/SweetingTech/TableTop_DM/actions/runs/44341566260/job/134932649555).
