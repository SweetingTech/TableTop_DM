# Section H hosted test results

The tested PR revision was `c47eddb87f6201d611183d96111a7ef56c7e74dd`. GitHub merged that exact
tree to `main` at `66df949d9cc5bb723bbc307f782ebdc979e41dc7`. [Pull request](https://github.com/SweetingTech/TableTop_DM/pull/135)

- The PostgreSQL integration job ran all 201 selected cases successfully. The party, autonomous
  invitation, coordination, and quest-transfer cases passed. These cases verify restart, normal
  death saves, one funded payout, and replay. [Integration job](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262738/job/140735504468)
- Chromium passed all 50 journeys. The two quest cases completed a main or alternate approach,
  read its progress, and claimed the reward. The alternate-route case showed the required item
  in both the offer and the personal journal. [Browser job](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262708/job/140735504036)
- The quality and image jobs passed. The independent GitHub review reports zero unresolved
  findings for the tested revision. [Quality and image](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262738) · [Review receipt](https://github.com/SweetingTech/TableTop_DM/pull/135#issuecomment-7226988620)

The [criterion map](acceptance.md) identifies the runnable source for each of the five Orderly
criteria and the shared resident journey.

The exact PostgreSQL job log records successful pytest progress for `test_party.py` (one
case), `test_party_coordination.py` (two), `test_party_runtime.py` (one), and
`test_quest_transfer.py` (two), followed by `201 passed, 800 deselected`. The case descriptions
below identify the actual assertions in the tested source. [PostgreSQL job log](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262738/job/140735504468)

## H1 — Party formation, consent, departure, hostility, and reunion

`test_resident_can_decline_join_leave_and_rejoin_without_body_access` runs once for ordinary
departure and once for hostile departure. A player forms the River Wardens with the goal
“Keep the ferry crossing safe.” `create_and_invite` asserts the invitation ID is its causal
event ID. The founder scene contains only the founder before consent, and the resident
scene receives the goal in the invitation while listing no parties. Only an authorized
controller can respond for the resident. The first response is `DECLINED`; attempting to use
that invite again returns 400 without a state change. A second invitation yields `JOINED` and
the two-member party scene. Leaving records `LEFT` or `HOSTILE_EXIT` and a personal reason
visible to the departing subject. A third accepted invitation returns `REUNITED` with the
exact prior departure event ID, and its retry returns the original event. [Lifecycle assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_party_api.py#L27-L134)

The party join mutates the in-world party projection using the ordinary resident body.
Throughout the join, the player's query for that resident's scene returns 403 and the
player's attempted command as the resident returns 403. In the PostgreSQL case
`test_party_invitation_and_consent_survive_restart_and_replay`, the pending invitation survives
a restart. The acceptance is idempotent across a second restart, the resulting party has
both bodies, scene authorization still returns 403, and replay reports `verified`. [Durable assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/integration/test_party.py#L18-L51)

## H2 — An ordinary resident makes its own decision

`test_resident_responds_from_pinned_motives` runs the same invitation against two pinned
resident dispositions. The visible invitation in the resident's trusted decision context has
motive `CARE`; the opaque persistent ID is withheld from that situation. The same context
setup checks that `PRIVATE_NPC_VOW` is absent from the player's scene. An authorized
`AUTONOMOUS` controller uses a normally scheduled character runner. The test inspects the
committed proposal: `command_type == "tabletop.party.respond"`, `input_origin == "NPC_POLICY"`,
the proposal's embodied ID is the resident, its invitation ID matches the witnessed offer,
and the result is `JOINED` or `DECLINED` according to the resident's disposition. Each
result changes membership accordingly, and the player's unauthorized scene query stays
403. The runner exhausts the assigned step and makes no second response. [Decision assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_party_runtime.py#L15-L111)

`test_resident_uses_pinned_motive_after_runner_restart` restarts the PostgreSQL app before
the decision and executes that same assertion helper. It confirms both party members and
the continued 403 for the player's request for the resident scene. [Durable assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/integration/test_party_runtime.py#L14-L25)

## H3 — Voluntary movement, leadership, resources, and testimony

`test_leadership_and_travel_are_separate_from_body_authority` rejects an outsider's plan
and a founder trying to force a resident to follow. The founder's `PLAN_UPDATED` specifies a
goal and waypoint. The resident's consent returns `FOLLOWING` while its position is still
unchanged. An action by the resident body moves it. `LEADER_CHANGED` transfers authority to
that resident. The former leader's next plan is rejected while the successor's succeeds.
A stale follow request fails. The founder stays at its original position and still lacks
access to the resident scene. `autonomous_waypoint` also exercises this movement without
a human resident controller: a runner step accepts the plan, the world clock advances, and
the next runner step commits `tabletop.spatial.move` for the resident to `(1, 1)` while
the founder's Y coordinate stays zero. [Leadership and movement assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_party_coordination.py#L41-L101) · [Autonomous step assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_party_coordination.py#L184-L226)

`exchange_at_cache` deposits one spear from personal inventory into the party cache.
A remote withdrawal returns 400. After the resident walks to the cache, it can withdraw
the spear. The cache empties, and the founder and resident inventories contain zero and
one spear, respectively. `test_hearing_does_not_follow_party_membership` delivers a nearby
whisper as an observation. After the resident walks beyond whisper range, a second
whisper is absent from that resident's observations even though it still belongs to the
same party. The PostgreSQL travel and cache cases assert that the party scene is identical
after restart and replay verifies. [Cache and testimony assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_party_coordination.py#L102-L181) · [Durable cases](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/integration/test_party_coordination.py#L14-L28)

## H4 — Alternate informant, inventory prerequisite, progress, and transfer

The crossing fixture funds a seven-gold reward from the bridge steward, requires one spear,
designates the ford warden as alternate contact, and sets separate north-bank and ford
objectives. An ordinary spell and two clock-driven death save rounds kill the steward. The
steward has no offer in the player's scene, and the designated warden offers the same quest.
A character lacking a spear receives 400 with a required-items error; with a spear, it can
accept. A committed spatial step to the ford resolves the alternate objective, leaving the
main objective at zero. A separate case with no designated alternate confirms a nearby
resident cannot take over a dead giver's offer by implication. [Prerequisite and alternate route assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_quest_transfer_api.py#L41-L139) · [No implicit delegation](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_quest_transfer_api.py#L234-L251)

The player offers transfer to the resident. Acceptance fails before the recipient meets
the same inventory requirement. Once the resident has the spear, their acceptance links
to the offer event and returns `READY`. The former holder's reward claim fails. The new
holder claims seven gold, the alternate contact spends nothing, and the old steward keeps
the remaining thirteen gold. The canonical quest shows the resident as owner and retains
the exact source command for the completed objective. A separate nontransferable quest
rejects the transfer and retains its original owner. [Transfer and escrow assertions](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_quest_transfer_api.py#L141-L227) · [Transfer rule assertion](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_quest_transfer_api.py#L254-L274)

## H5 — One resident's campaign across autonomy, human control, death, and restart

`test_resident_campaign_crosses_control_restart_and_replay` invokes the single
`resident_campaign` journey against PostgreSQL. That journey starts with
`autonomous_waypoint(..., human_owner=True)`: a distinct typed controller authorization
does not itself switch the resident from the autonomous mode. The resident joins, agrees
to the party plan, and performs its own movement. A human attempt to make it leave is
rejected while it is paused under the previous controller. The player then successfully
sets `HUMAN` with the current epoch, and the runner reports zero work for that body.
The player uses the new epoch to leave because “My brother needs me on the night watch.”
Both the resident's empty party view and the founder's remaining membership are asserted.
After the bridge steward dies, this same resident accepts the transfer of the ready ford
task, retains its objective source command, and receives the escrow once. The app and
player reconnect, the same reward key returns the identical event, and the resident
remains the quest owner and outside the party. The integration wrapper then verifies branch
replay. The paired durable crossing case also asserts that the durable ledger mark is
unchanged after retry. [One resident's journey](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/unit/kernel/test_quest_transfer_api.py#L277-L360) · [PostgreSQL restart, idempotency, and replay](https://github.com/SweetingTech/TableTop_DM/blob/c47eddb87f6201d611183d96111a7ef56c7e74dd/tests/integration/test_quest_transfer.py#L14-L49)
