# Section G review follow-up

This report covers the five evidence gaps from the latest Task 8 review and links the
remaining four criteria to their passing cases. The runtime and compiled console are
from `2016982f329a40449f58142787c191d38fcde8f2`. The test revision is
`45fcc5940e9da5e8e3940e62f249a3dd613f053f`. The change adds tests and documentation.

## G1. Authorship and complete dialogue linkage

In [the durable dialogue test](../../../tests/integration/test_speech_combat_behavior.py),
four authenticated human utterances each return a distinct event ID. The stored rows join
the accepted commands, canonical events, and private choice evidence by exact event ID.
The assertions check human origin and authorship, the actual utterance, the player, the card,
the body, conversation readiness, and the choice of whispered greeting among offered options.
Five operator utterances are classified separately and contribute zero human preference rows.
[The NPC runtime test](../../../tests/integration/test_population_runtime.py) distinguishes
policy and model origins for character-policy actions in PostgreSQL. The model case uses a
deterministic provider fixture and checks the recorded model version. [The campaign and
trial test](../../../tests/integration/test_section_g_campaign.py) records director and
stand-in origins separately. [The masked attack case](../../../tests/integration/test_section_g_proof.py)
checks that the human choice frame and offered options exclude the unperceived attacker.

## G2. Comparable speech, priorities, relationships, risk, and tactics

The dialogue profile cites the four human events as both contextual and cadence evidence,
reports confidence of four sevenths, survives restart, and drives a short whispered reply.
The [versioned profile regression](../../../tests/integration/test_section_g_proof.py)
keys movement and choice profiles to the same player and card. Four comparable choices offered
self-healing and healing a witnessed helper. The learned score favors helping that character,
and the canonical worker receipt in the [campaign test](../../../tests/integration/test_section_g_campaign.py)
executes that preference and cites the four source events.
The peaceful-character regression starts with guard preferred over attack. Four human attacks
among those same offered options raise the attack score above guard. The profile retains the
exact attack event IDs, offered sample counts, and four-sevenths confidence.
[Policy tests](../../../tests/unit/kernel/test_speech_combat_behavior.py) demonstrate learned
withdrawal, and [tactical tests](../../../tests/unit/kernel/test_tactical_choices.py) verify
that an option absent from the human examples retains its authored fallback.

## G3. Visible contradictions and authored fallback

The [peaceful-character regression](../../../tests/integration/test_section_g_proof.py)
pins a peaceful backstory, records the initial fallback, and then commits four real human
attacks. The owner and operator each query the normal private choice-profile route and see
the same correction notice asking them to review the card or history. The profile retains
the same binding and attributes the contradiction to the four committed sources.
The campaign test also runs a companion with no human history and checks that its pinned
peaceful backstory drives de-escalation.

## G6. Identity during explicit handoff, timeout, reconnect, and return

The [Chromium journey](../../../tests/e2e/test_controller_runner_isolated.py) reads the pinned
binding through the signed-in browser. It matches the character ID and body ID to the original
card, then compares the entire pinned record after an explicit handoff, a disconnect timeout
and reconnect, and return to human control. The journey asserts the new controller epoch,
the visible campaign pause policy, the opt-in disconnect setting, and the recap.
[The durable world-pause cases](../../../tests/integration/test_world_time.py) separately
check commit fencing and runner resume.

## G7. Dedicated authority with a separate human profile

The [durable rebuild test](../../../tests/integration/test_section_g_proof.py) queries the
executor's actor kind and verifies it has no browser user account. PostgreSQL records exactly
the expected capability set in the one assigned world. With the executor set as the database
actor, the entity grant permits the assigned body and denies the neighboring helper. A fresh
worker with no browser client commits the bounded action. Takeover revokes the executor's
body authority. The [campaign receipt test](../../../tests/integration/test_section_g_campaign.py)
joins the accepted command and event to the private receipt and checks that the dedicated
executor differs from the attributed player and that the receipt cites that player's examples.

## Previously accepted criteria

| Criterion | Direct evidence |
| --- | --- |
| G4 | [Durable profile rebuild and trial isolation](../../../tests/integration/test_section_g_proof.py) preserve the original human event set after restart and exclude stand-in actions. The [campaign trial](../../../tests/integration/test_section_g_campaign.py) verifies the alternate branch and a director action leave canonical history unchanged. |
| G5 | [The durable takeover race](../../../tests/integration/test_section_g_proof.py) commits one new controller epoch and one movement. The prepared old executor proposal is denied. |
| G8 | [Scoped recap access](../../../tests/integration/test_section_g_proof.py) and [browser adapters](../../../tests/e2e/test_controller_runner_isolated.py) verify access and the wire requests. [The durable in-progress action test](../../../tests/integration/test_controller_runner.py) verifies the original action and receipt survive takeover exactly once. |
| G9 | [The durable campaign](../../../tests/integration/test_section_g_campaign.py) runs solo, mixed, and all-autonomous play with real workers. The first stand-in follows learned choices and the companion with no history follows its backstory. The test verifies the character's situation stays unchanged at handoff. |

The [prior verification and hosted runs](completion-proof.md) remain available for comparison.

## Focused test results

The isolated PostgreSQL run passed all ten cases across the Section G proof, dialogue,
NPC runtime, and mixed campaign tests. Chromium passed the disconnect and return journey.
Four focused policy tests passed for withdrawal, authored fallback, comparable aid, and
unoffered options.
