# API and user workflows

For durable command receipts, private inspection authorization is read from the current protected
world grant after execution, using the same `sim.has_world_capability` primitive as RLS. A cached
in-process DM grant cannot survive another API process's revocation. New responses and cached
retries are both redacted after revocation; privileged inspection remains available when the
current exact-world grant allows it. Reference mode uses its existing world-scoped authority.

`POST /api/v2/commands` presents quest/offer results without private projection deltas unless
the submitting actor has `world.read.all` in the command's exact world. Quest source commands,
unperceived target IDs and offer provenance cannot leak through accept/trade/reward receipts or
cached retries. The committed receipt, event, hash and replay records are unchanged internally;
ordinary public results and scene synchronization still describe the action. Client parameters
cannot request privileged presentation or grant capabilities.

Quest contract `tabletop-quests-2.0.0` uses `POST /api/v2/commands`:

- Manager `tabletop.quest.configure`: `{giver_id, title, description, objectives, reward_gold?,
  reward_items?}`. One to eight immutable objectives combine with AND. Rewards reserve available
  giver gold and inventory at creation; titles/descriptions are explicitly public in-world text.
- Objectives each have `description` plus one discriminated definition: `kind: "MOVE"` with
  `x,y,zone_id?,z?`; `kind: "DEFEAT"` with distinct `target_ids` (all must be defeated once);
  `kind: "TRADE"` with `side: "BUY"|"SELL",counterparty_id,item,quantity`; or `kind: "WEED"`
  with `units`. Targets/counterparties must exist in the same branch. DEFEAT means a genuine
  positive-to-zero HP outcome caused by the owner's attack/spell, not necessarily permanent death.
- Controlled `tabletop.quest.accept`, `tabletop.quest.advance` and `tabletop.quest.claim` accept
  only `{quest_id}`. Accept fixes the body owner; advance only reviews recorded status. New
  requests cannot supply `amount`, `target`, source evidence, ownership or reward overrides.
- Manager `tabletop.quest.cancel` accepts `{quest_id}` and returns any unsettled funded reward once.

Accept and claim require a capable, visible, adjacent giver and reserve both participants for six
seconds with encounter/readiness checks. Claim requires every objective satisfied; the body must
return to the giver and cannot claim twice. Cancellation/claim retain terminal audit state.
Offscreen WEED progress counts only newly committed work after acceptance, excluding action-busy,
blocked or pre-acceptance work. The ordinary command receipt remains the retry authority.
Scenes expose nearby `quest_offers` as public descriptions/rewards; only the observing body's
`quests` includes its journal, with active tasks first and up to 32 recent entries. Full terminal
history remains canonical. Source commands, raw target/counterparty IDs and owner metadata are
excluded from these views. Fiction context version `character-context-1.6.0` replaces quest IDs
with local task references. The console prepares `/quest accept|status|claim <quest id>` intents
from the offer or personal journal; choosing a button focuses the draft and sending commits.
This wires enforcement and observed opportunities; autonomous goal selection remains checklist F.

Trade contract `tabletop-trade-2.0.0` uses these typed commands through `POST /api/v2/commands`:

- `tabletop.economy.configure_offer`: world-manager capability `entity.control`, with
  `{maker_id, side: "SELL"|"BUY", item, quantity, unit_price, valid_for_seconds?}`.
- `tabletop.economy.offer`: controlled capable maker with `entity.act`; same terms without
  `maker_id`. SELL reserves its inventory; BUY reserves its gold. Default lifetime is 86400 seconds.
- `tabletop.economy.trade`: controlled capable taker, `{offer_id, quantity?}`. Quantity defaults to
  one. No caller-supplied price, item, counterparty or direction is accepted. A zero-price gift
  still requires an explicit maker offer. Contact, perception, funds/stock, encounter and both
  bodies' readiness are checked atomically; the exchange occupies both bodies for six seconds.
- `tabletop.economy.withdraw_offer`: controlled maker, `{offer_id}`; normal action cost.
- `tabletop.economy.cancel_offer`: manager cancellation, `{offer_id}`; no physical action cost.

Unused escrow returns on cancellation/expiry and active offer state is removed. Old committed
trade receipts still replay on their original key; new requests must use the offer contract.
The perceived scene exposes `trade_offers` only on inspected contact-range makers (and one's own
body): offer ID, side, item, available quantity and unit price. No private book, source command,
run provenance or expiration metadata is exposed. Context version `character-context-1.6.0`
uses fiction references instead of offer IDs. This exposes opportunities without yet adding an
autonomous trading policy. In the console, choose a quote, then send the prepared intent, or use
`/trade <offer id> [quantity]`, `/offer buy|sell <item> <quantity> <unit price>` and
`/withdraw <offer id>`. Stale quote rejection preserves the draft and refresh never invents offers.

Rules `tabletop-action-rules-1.2.0` derive attacks from a canonical body's ability scores,
equipped registered weapon and training. Unarmed/spear attacks use Strength; a shortsword uses
Dexterity when it is higher. Attack bonus is the ability modifier plus proficiency if trained;
damage bonus is that ability modifier. Proficiency is 0..6 and scores are 1..30. Poison/fear still
apply disadvantage, and existing perception, range, incapacity, clock/initiative and resource
checks remain mandatory. Old flat bonus fields cannot override a body with configured scores.

New character bodies pin starting scores, level-derived proficiency (2..6) and training for all
three registered weapons. No class gate prevents using owned gear; an untrained weapon simply
omits proficiency. Legacy bodies without scores retain their explicit old flat profile until
an authorized manager configures them; no mutable card data is consulted to guess their stats.

`tabletop.body.configure` is a manager-only typed definition command requiring world-scoped
`action.propose` and `entity.control`. Parameters are `entity_id`, `ability_scores` (the six named
scores, omitted entries default 10), `proficiency_bonus` (default 2), `trained_weapons` (up to 3
registered IDs), `known_spells` (up to 2 registered ARCANE_BOLT/MEND IDs) and `equipped_weapon`
(default UNARMED). The defaults are the project's starting definition, not caller-selected attack
rolls or damage. A configured non-unarmed weapon must already be owned. The command cannot
change HP/mana/inventory, revive a body, supply an attack bonus or invent weapon/spell rules.
It preserves existing action costs and conditions. Use `tabletop.resources.configure` separately
for known resource capacities. Retries return the original definition receipt without resetting
subsequent equipment or resources.

`/equip UNARMED|SHORTSWORD|SPEAR` submits controlled `tabletop.equipment.equip` with only
`weapon_id`. A capable, authorized body may ready its owned weapon under ordinary six-second
action/initiative enforcement. Unknown, unowned, already equipped or forged-stat attempts fail
without writes. Successful changes emit a sight-scoped in-world description, not internal rules
metadata. The live sheet exposes only allowlisted own-body scores and derived bonuses through
its existing state request; authored-card values never stand in for unavailable canonical stats.

World managers submit `tabletop.encounter.start` with only `participants` (2..64 distinct living
body UUIDs), requiring world-scoped `action.propose` and `entity.control`. A current run clock is
required. The kernel allocates a recorded action seed and rolls d20 + floor((DEX−10)/2) from each
canonical body's ability scores; legacy bodies without that field use DEX10. Sort descending by
total, then bonus, then UUID. New character bindings pin their authored starting scores into the
body; later card edits cannot rewrite ability scores or an already rolled order.

Policy `tabletop-initiative-1.0.0` gives each participant a six-second window in that fixed order,
repeating on the shared clock. Starting an encounter does not advance time. Physical actions still
reserve their ordinary body-owned duration; fast movement may use multiple steps in a window,
while a six-second action consumes its readiness. Speech and camera changes remain legal off turn.
A missed, sleeping, incapacitated or dead participant's window passes as time advances. Other
bodies continue working and living; clock boundaries enforce participant readiness for offscreen
work too. These continuous-time rules do not implement a separate frozen-world turn engine.

Out-of-turn attempts return `invalid_operation`400 without writes or costs; runners wait without
spending failure/step budgets. Concurrent attempts serialize under the branch lock and retries
return the original receipt. Players see only their own `action_wait_seconds`, never other
bodies' initiative rolls, encounter IDs, future windows or seed provenance in sensory context.
Physical interaction with someone in a different/unjoined encounter is rejected. A body cannot
belong to overlapping encounters or begin manual rest during combat. World managers choose all
participants without class/party restrictions; to change the roster, stop and start an encounter.

`tabletop.encounter.stop` accepts only `encounter_id` under the same manager capabilities. It
removes the active projection while preserving append-only command/event history and receipts;
it does not refund body action costs. A current-run manager can end a previous run's stale
encounter. There may be32 active encounters; completed fights do not consume a lifetime quota.

The console accepts `/stabilize <perceived target name or id>`, submitting
`tabletop.combat.stabilize` with strict `target_id` parameters. A capable controlled body must
be adjacent to a visible living body at 0 HP. Successful first aid stabilizes it and reserves
six simulated seconds; rejected/repeated actions do not spend time twice. Cast/invoke MEND can
also rescue a living 0-HP body with known positive maximum HP, but never revive a dead one.

New damage-induced defeats retain private physical seed provenance and pending death saves.
Every six seconds, a d20 of 10+ succeeds, a natural 1 adds two failures and a natural 20 restores
1 HP. Three successes stabilize; three failures mark death. Stable bodies with known positive
maximum HP recover 1 HP after one simulated hour. Existing unrelated conditions remain intact.
Pending saves on clockless branches start when their clock first advances. Old zero-HP bodies
without a new defeat record are not assigned fabricated past rolls; first aid remains available.
Clock advance, retry and restart preserve the same indexed saves. Save seeds/counters are not
part of sensory scene/context contracts. Whole-section C acceptance remains a separate gate.

`/rest short|long` submits the controlled `tabletop.rest.start` intent, with only `kind` set to
`SHORT` or `LONG`. The current run's configured clock, positive HP, capability and entity control
are required. A busy body or one with an active manual activity/enabled routine cannot start.
The existing canonical activity owns progress: starting rest grants no instant resources and does
not advance global time. Successful physical effort or taking damage cancels a manual rest;
speech and camera changes do not. Incapacity or displacement cancels it on clock reconciliation.
An authorized manager can also cancel through the existing `tabletop.activity.cancel` command.

`tabletop-rest-1.0.0` awards a one-time ceil(max_hp/4) HP benefit after 3600 uninterrupted seconds.
After 28800 seconds, a long rest restores HP/mana to known caps if at least 86400 seconds have passed
since the prior long-rest benefit. It also receives the earlier hourly benefit. An ineligible
long rest still reduces fatigue; it cannot refill mana early. These are the project's versioned
rules, not a claim to implement every tabletop ruleset. Recovery never removes independent
conditions, revives a dead/downed body, or infers missing capacity from mutable character cards.
Offscreen routine REST/SLEEP uses the same uninterrupted thresholds and cooldown. Interruptions
reset recovery eligibility; accumulated gardening/routine work retains its separate progress.

Newly bound bodies initialize `max_mana` from starting mana. Legacy bodies with unknown caps do
not receive invented refills. A world manager may submit `tabletop.resources.configure` with
strict `entity_id`, `max_hp` (1..100000) and `max_mana` (0..100000), requiring `entity.control` and
`action.propose`. Raising caps does not refill resources; lowering below current HP/mana is
rejected atomically. Players cannot use this command to change their own caps. Trials remain
isolated, and retries return the original receipt without resetting progress or granting twice.

`tabletop.condition.apply` is a registered typed command for world managers. Its strict parameters
are `target_id`, `condition` and `duration_seconds` (1..86400). Conditions are case-insensitive
`stunned`, `incapacitated`, `unconscious`, `paralyzed`, `poisoned` or `frightened`; death is not a
temporary condition. The target must exist in the branch, and that branch must have the current
run's clock. Required world capabilities are `entity.control` and `action.propose`; another
world's DM role grants no authority. The result reports `effect_id`, target, condition and absolute
`expires_seconds`. Clients cannot choose source IDs/expiry, and at most32 timed sources fit per body.
Retries return the original receipt even after expiry; they do not reapply the condition.

`tabletop.divine.bless` retains `target_id`, `blessing` and `duration_turns`. With a matching clock,
each turn lasts six simulated seconds and the result includes `expires_seconds`. Separate grants
expire independently. Without a clock, the legacy remaining-turn record is retained until the
first clock advance anchors it. Blessings remain descriptive grants; no new stat bonus is inferred
from their names. Current permanent conditions and historical receipts remain unchanged.

The live sheet reports active condition names through its existing typed fields; private creating
command/run metadata is excluded. Clock advancement processes intermediate boundaries, so an NPC
stunned for five seconds during a ten-second advance can only work for the remaining five.

On a configured clock, successful controlled physical commands reserve per-body action time. Physical
actions cost six simulated seconds and a five-foot movement step costs
ceil(30/body speed), at least one second. Callers cannot choose these costs. Before readiness,
new actions return existing `invalid_operation`400 without writes; retrying an already committed
idempotency key returns its original receipt. Paused clocks can be advanced explicitly by their
authorized operator; actions do not move global time. Unconfigured worlds stay untimed.
Speech, console interpretation and quest bookkeeping do not spend physical action time. The
camera/control-mode command is presentation only: it does not wait for readiness, wake a body,
or consume/reset its action budget. Controlled-entity authorization still applies. The
own-body `PerceivedEntity.action_wait_seconds` reports remaining readiness; it is null for
other bodies. Character proposals omit impossible candidates and unattended runners wait without
spending budgets, including proposal/commit races. A guard expires at its six-second boundary
through either a clock tick or explicit advance. This does not add full initiative, timed
condition/blessing definitions or death/recovery policy.

`PATCH /api/v2/player/characters/<character_id>` rejects supplied `status`, `current_hit_points`,
`maximum_hit_points`, `armor_class`, `speed` or `ability_scores` after `entity_id` is bound. A non-null `world_id`
that differs from the bound world is also rejected. This applies to administrators as well as
owners and returns the existing `invalid_operation`400 without partial identity/card writes.
Use authorized world actions for current physical effects. Same-world/identity edits remain
supported; unbound cards retain their starting-stat controls. Existing null-as-omitted PATCH
semantics are preserved, so null cannot detach a body or clear its world through this route.

`GET /api/v2/player/characters/<character_id>/live-state` returns `character_id`, authored
`card_version`, `source` (AUTHORED or KERNEL), and optional typed `body`. KERNEL body fields include
world/branch/entity IDs, projection_version, HP/max HP, status, armor, speed, mana, owned inventory,
equipped weapon, learned spell IDs and conditions. No client-selected run/branch is used; the
world's canonical branch is authoritative. Status distinguishes ALIVE, ASLEEP, INCAPACITATED,
DEFEATED and DEAD. Reading neither changes card data nor commits a simulation action.

The caller must own the card or be an administrator, retain world access, and control/inspect the
bound body under the existing scene authority rules. Other owners and revoked roles receive403.
Unbound cards return AUTHORED/body:null; missing bound metadata/projection returns
`character_body_unavailable`409. Success and errors use Cache-Control:no-store.

The Player Dashboard reads this endpoint for the selected sheet. Bound resources are read-only;
unbound cards retain starting HP/status controls after an explicit AUTHORED response. A visible
tab polls serially every five seconds; visibility changes and Refresh request fresh state.
Changing character or leaving the sheet aborts and discards obsolete reads. Errors clear displayed
resources rather than falling back to card values; 401/403 stop automatic polling until manual
Refresh. Background reads preserve unsaved identity edits. Refresh characters separately reloads
the card library and membership list.

Voluntary controlled commands reject incapacitated bodies consistently. A valid human command
can wake ordinary sleep, including attack/cast/invoke; an invalid attempt does not wake or spend
resources. Autonomous sleepers retain the existing suspension behavior. Own scene status reports
`INCAPACITATED` or `DEAD` for the action catalog; other bodies' private condition lists are not
exposed through this mapping. MEND cannot resurrect a dead body with stale positive HP.

`POST /api/v2/cognition/decide` supports `mode: "CHARACTER"` with required `world_id`, `branch_id`,
`run_id`, `embodied_entity_id` and `idempotency_key`. No other fields are accepted. The response
is the existing character receipt (`execution_mode: "PROPOSAL_ONLY"`, `committed: false`) with
`Cache-Control: no-store`. The same key/scope/actor on the entity-scoped `/character-proposals`
route returns the same receipt. Identity, scene, history and actions are server-derived; kernel
submission is a separate authorized step. Omitted mode preserves the privileged legacy
EVALUATION request/201 response; explicit `mode: "EVALUATION"` is also accepted.

The Flask application serves the React client and a JSON API from the same origin. Browser pages
live under `/v2/*`; API resources live under `/api/v2/*`. UUIDs are serialized as strings and
timestamps use ISO 8601.

Attack contract 2.1.0 allocates physical roll seeds on the server. The optional proposal `seed`
remains decision/evaluation provenance and cannot select a live attack roll. Submit a new
idempotency key for a distinct action; retry the original key to recover its original outcome.
Authorized canonical command receipts include private `result.randomness` provenance. Character
observations and generated dialogue receive only their masked physical facts, never this proof.

## Authentication

### Browser sessions

`POST /api/v2/auth/login` accepts a username and password. A successful response sets the
HTTP-only `ttdm_session` cookie with `SameSite=Lax`; HTTPS deployments also receive the `Secure`
flag. The server stores only a hash of the session token.

Login remains public but applies the same write-origin checks as authenticated browser writes.
Cross-site Fetch Metadata, a foreign or opaque Origin, and malformed Origin ports are rejected
before credentials can create a session cookie. Same-origin and headerless automation login work.

Useful routes:

| Method and route | Purpose |
| --- | --- |
| `POST /api/v2/auth/login` | create a 12-hour session |
| `GET /api/v2/auth/session` | return the authenticated account and role summary |
| `POST /api/v2/auth/change-password` | replace the current password and rotate sessions |
| `POST /api/v2/auth/logout` | revoke the current session and clear the cookie |
| `GET /api/v2/profile` | retrieve the current profile |
| `PUT /api/v2/profile` | replace editable profile fields |

The bootstrap `admin` / `admin123` credential is accepted only as an installation entry point.
That account has `password_change_required=true`; all protected application routes except session
inspection, password change, logout, and health return `403` until the password is replaced.

### Automation compatibility

Local automation may send `X-TTDM-Operator-Token` with the value configured in
`TTDM_OPERATOR_TOKEN`. The operator token is a machine-level compatibility boundary, not a user
account and not a substitute for player/DM role assignment. Requests without a cookie or token
are accepted only under the fail-closed loopback Host/Origin policy.

## Roles and authorization

- `ADMIN` is global.
- `DM` and `PLAYER` are assigned per world.
- A combined DM + Player account simply has both world roles.

The frontend hides unavailable workspaces, the API enforces the matching product role, the
simulation layer resolves world-scoped actor authority, and PostgreSQL RLS checks protected rows.
UI visibility is never treated as authorization.

## Discovery and health

| Method and route | Purpose |
| --- | --- |
| `GET /healthz` or `/api/v2/health/live` | process liveness |
| `GET /readyz` or `/api/v2/health/ready` | dependency and migration readiness |
| `GET /api/v2/meta` | runtime mode and contract metadata |
| `GET /api/v2/bootstrap` | worlds, active context, authenticated actor, and client bootstrap data |
| `GET /api/v2/commands/contracts` | registered typed command schemas |
| `GET /api/v2/personas/schema` | persona dimensions, dependencies, and constraints |

Readiness returns `503` with per-dependency details if a configured PostgreSQL, Redis, Qdrant, or
migration check is unavailable.

## Administrator workflow

1. Sign in and complete the mandatory password change.
2. Open Admin Dashboard and create accounts with a temporary password.
3. Assign `ADMIN` globally only when platform administration is required.
4. Grant `DM`, `PLAYER`, or both for each relevant world.
5. Create or inspect worlds, actors, entities, runs, snapshots, and trial branches in Control
   Plane.
6. Review append-only account activity in the admin audit view.

Account routes:

```text
GET    /api/v2/admin/users
POST   /api/v2/admin/users
PATCH  /api/v2/admin/users/{user_id}
DELETE /api/v2/admin/users/{user_id}
PUT    /api/v2/admin/users/{user_id}/password
PUT    /api/v2/admin/users/{user_id}/roles
PUT    /api/v2/admin/users/{user_id}/worlds/{world_id}/roles
GET    /api/v2/admin/audit
```

The final administrator cannot remove their own last admin role, disable themself, or delete
themself, and the last administrator who can still sign in cannot have their role removed, be
disabled, or be deleted by anyone. Disabled administrators do not count toward that guard, because
a disabled administrator cannot administer anything. Password resets revoke the user's active
sessions and require another password change.

Five failed logins lock an account for fifteen minutes. Attempts made during a lock are not
recorded, so they neither extend nor renew it, and the failure count restarts once the window
lapses — an account cannot be held locked by guessing at its username.

## Player workflow

1. An administrator grants the account `PLAYER` for a world.
2. The player opens Player Dashboard and chooses that world.
3. They create a character by:
   - building one from editable fields;
   - generating one deterministically from a seed; or
   - importing a JSON character template.
4. The dashboard displays class, ancestry, background, level, hit points, armor class, movement,
   ability scores, and `ALIVE`, `DEAD`, or `RETIRED` status.
5. A DM can assign that character to the player's game membership.

Routes:

```text
GET    /api/v2/player/characters
POST   /api/v2/player/characters
PATCH  /api/v2/player/characters/{character_id}
DELETE /api/v2/player/characters/{character_id}
GET    /api/v2/games
GET    /api/v2/games/{game_id}/sessions
```

Character writes are owner-scoped unless an administrator is acting through an administrative
flow. Imported templates are parsed and validated before persistence.

Character create/import and patch accept `authored_identity`: `backstory` (up to 12,000 characters)
and `motives`, `values`, `bonds`, `secrets`, `initial_known_facts` (each up to 20 nonempty strings
of 500 characters). Unknown identity fields, non-string entries, and over-limit input fail before
persistence. Whitespace is trimmed. Patch replaces the complete identity when supplied; omitting
it preserves the existing identity. An empty object clears it. Character sheet edits cannot use
the reserved `_authored_identity_v1` storage key. Legacy records receive an empty identity.

Responses include the typed identity and `card_version`, a SHA-256 content identifier over the
card schema, name, species, class, background, level, ability scores, and authored identity.
Wounds, status, ownership, world/body assignment, equipment, and timestamps do not alter this
identity version. This identifies current content; it is not an archive of prior cards or a
replacement for canonical entity state. Existing private JSON sheet storage persists the identity
without a schema migration. DM assignment lookups still return summaries only.

Starting knowledge is player-authored fiction, not a verified world fact or a sourced memory.
This change does not feed the identity into model prompts, minds, lore retrieval, or live decisions;
trusted approval and explicit persona/mind/body bindings remain required.

When a DM assigns a character to a game membership, the portal character is linked to a kernel
embodied entity. The player receives `entity.act` plus control of that specific body; this never
confers administrative `entity.control` over the world.

## Perception-scoped game workflow

The Player Game Console never reads canonical entity positions or the raw event ledger. It lists
authorized embodied viewpoints and loads a `PerceivedScene`:

```text
GET /api/v2/worlds/{world_id}/viewpoints
GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{entity_id}/scene
GET /api/v2/events/{event_id}/perceptions       # privileged inspection only
```

Normal prose submits `tabletop.dialogue.speak`, an embodied sound emission. The console supports
`/move`, `/attack`, `/guard`, `/stabilize`, `/cast` and `/invoke` through their typed movement/combat/magic
contracts. Unknown slash commands show those supported actions, retain the draft and make no
command request. API callers can explicitly submit uninterpreted OOC/interface text through
`tabletop.console.submit`; recording that proposal does not execute a physical action.
The scene contains only current perceived entities and subjective
observation presentations, with detail levels from anonymous `PRESENCE` through `INSPECTED`.

Accepted embodied `POST /api/v2/commands` receipts include `scene_refresh` with `world_id`,
`branch_id`, `observer_entity_id`, `event_id`, and the committed `projection_version`. The client
reads the same scene with `?after_event_id={event_id}`; the response adds `refresh` containing
`event_id`, `ready`, and `observed`. Normal scene reads omit this metadata. Scene responses use
`Cache-Control: no-store`. The cursor is authorized for the submitting actor and exact body and
timeline; it grants no additional visibility. `ready` requires the expected subjective observation
when the frozen event-time grant produces one. Unperceived actions are ready without inventing
an observation. Durable reads hydrate a request-local mind snapshot from the RLS repository, so
separate projector processes are visible without replacing the API's shared projector cache.

The console polls every 200 ms for at most eight seconds after acceptance, requiring both the
canonical version and observation boundary. Only authorized observations enter the feed, keyed
by source event. A timeout or read failure reports that the action was accepted and offers a
read-only retry. Writes and post-acceptance reads never fall back to successful demo data.

Continuous console updates use serial, cancellable polling every 2.5 seconds while visible,
plus focus/online resynchronization. Reads remain perception-scoped. Older versions and obsolete
responses cannot replace newer scenes, while newly projected observations at the same version
still appear. The chosen body stays pinned; changing an unavailable assignment requires an
explicit character choice, clearing drafts, accepted-action cursors and observations. Background
refresh preserves the current draft/focus. Interrupted reads label the last confirmed scene and
disable actions. Authorization failures clear it and stop polling until an explicit retry.
The human scene response includes `experience_ready`; actions wait for the body's already
committed observations to finish projecting. This interface metadata never enters character
cognition. Missing runs/bodies, inspect-only views, unsupported commands and stale control are
actionable states. Initial live read failures also never become demo scenes.

DMs configure map presentation through the normal command endpoint:

```json
{
  "command_type": "tabletop.map.configure",
  "world_id": "<world UUID>",
  "branch_id": "<branch UUID>",
  "run_id": "<run UUID>",
  "idempotency_key": "map-world-v1",
  "parameters": {
    "zone_id": "world", "name": "Harbor yard",
    "min_x": -4, "max_x": 4, "min_y": -4, "max_y": 4,
    "image_path": null
  }
}
```

Bounds are inclusive grid-cell coordinates, with tokens at cell centers. Optional images must
be local `/static/` assets and are public presentation for viewers of that perceived zone. This
does not create physics zones or reveal hidden entities. Each branch supports up to 128 maps.
The human scene response adds only perceived-zone `map_presentations`; these never enter character
cognition. The console offers known-zone selection and every perceived entity with known
coordinates. Unpositioned entities stay in the list without an invented location. Without usable
configured extents it explicitly auto-fits a coordinate grid to known positions rather than
clamping different coordinates onto an edge.
World/viewpoint changes cancel pending reads and clear drafts, focus selection, and receipt state;
late command responses cannot populate the new viewpoint. This is per-action refresh, not yet
cross-client continuous updates.

## Dungeon Master workflow

1. An administrator grants `DM` for a world.
2. The DM creates a hosted game for that world.
3. They set status, description, player limit, safety notes, and house rules.
4. They invite eligible users as Player or Co-DM, assign characters, and track membership status.
5. They schedule sessions, update public notes, and maintain DM-only notes.

Routes:

```text
GET    /api/v2/games
GET    /api/v2/dm/worlds/{world_id}/eligible-users
GET    /api/v2/dm/games/{game_id}/users/{user_id}/characters
POST   /api/v2/dm/games
PATCH  /api/v2/dm/games/{game_id}
DELETE /api/v2/dm/games/{game_id}
PUT    /api/v2/dm/games/{game_id}/members
DELETE /api/v2/dm/games/{game_id}/members/{user_id}
POST   /api/v2/dm/games/{game_id}/sessions
PATCH  /api/v2/dm/games/{game_id}/sessions/{session_id}
```

DM notes do not appear in player responses. Co-DM membership requires the user's DM world role;
Player membership requires the Player world role.

The roster editor explicitly selects Player or Co-DM and supports assigning a character on
invitation or updating an existing member. Its character lookup requires game-host authority
and a target account with Player authority in that world; it returns only character ID, name,
class, level, and status for characters belonging to that player and either this world or no
world yet. It excludes character sheets and backstory. Assignment rejects missing characters,
wrong owners, and characters bound to another world. Choosing Co-DM clears the character selection.

Assignment checks for an unfinished canonical LIVE run before any preparation. Body creation and
card/persona binding are retryable preparation stages: a staged body has no human controller.
The final seat edit and `tabletop.entity.set_controllers` commit together. A failed final edit
leaves the prior seat/control intact; retry reuses the prepared body and binding. Existing join
times survive retries. Switching characters revokes the old body's control unless another game
still assigns it to the same human.

Deleting a member explicitly removes that human seat. On last-seat removal it keeps the body,
resources, card, persona and experience, clears human control, pauses any autonomous runtime and
increments its epoch to fence queued actions. The account's independent world roles remain.
Reinviting the same character restores its human control and preserves history. Removal is
different from a player handing off to an autonomous stand-in or disconnecting from a browser.

Changing the selected user or membership role immediately clears old character choices and lookup
errors, and disables player saves until the new lookup settles. Obsolete responses cannot replace
the current user's choices. Changing games remounts the roster editor for that game.

## World and command workflow

Control-plane collections:

```text
/api/v2/worlds
/api/v2/actors
/api/v2/worlds/{world_id}/actors
/api/v2/worlds/{world_id}/entities
/api/v2/runs
/api/v2/worlds/{world_id}/runs
/api/v2/snapshots
/api/v2/worlds/{world_id}/snapshots
/api/v2/branches
```

Submit a typed command:

```http
POST /api/v2/commands
Content-Type: application/json

{
  "world_id": "...",
  "branch_id": "...",
  "run_id": "...",
  "embodied_entity_id": "...",
  "command_type": "tabletop.spatial.move",
  "parameters": {"dx": -1, "dy": 0},
  "idempotency_key": "player-turn-42-move-1",
  "seed": 42
}
```

The kernel validates that the run belongs to the world and branch, resolves the command schema,
checks world-scoped capability and entity control, commits one transaction, and returns a receipt
with state/event provenance. Reuse an idempotency key only to retry the exact same logical command.

### Battlefield control modes

The command registry includes engine-neutral hooks for one continuous battle world:

```text
tabletop.battlefield.set_control_mode
tabletop.battlefield.issue_squad_order
```

`set_control_mode` accepts `TACTICAL`, `THIRD_PERSON`, or `FIRST_PERSON`. It changes the
commander's control-mode projection without replacing the entity, weapon, health, squad, enemies,
or encounter. `issue_squad_order` accepts `FOLLOW`, `HOLD`, `FOCUS`, `SPREAD`, or `REGROUP` and
keeps follower AI active while the leader is under direct control.

Future renderers consume `BattlefieldFrame` values built from an explicit authorized visible
entity set and return `BattlefieldControlInput` values for translation into these and other typed
commands. Camera mode does not grant event or entity visibility. See
[Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md).

The acting actor is never taken from the request. A browser session always acts as the actor its
account owns, so `actor_id` may be omitted; sending a different one is rejected with
`permission_denied`. Only the operator token may name another actor, through the request body or
`X-TTDM-Actor-ID`, because automation has no account of its own. The same rule governs every route
that resolves authority or visibility from an actor: `GET /api/v2/events`,
`GET /api/v2/entities/{entity_id}/mind`, `POST /api/v2/cognition/decide`, and
`POST /api/v2/events/{event_id}/observe`.

Read visible events with `GET /api/v2/events?world_id=...&branch_id=...`. Create a snapshot-based
trial with `POST /api/v2/snapshots/{snapshot_id}/branches`, inspect replay with
`GET /api/v2/branches/{branch_id}/replay`, and submit an approved consequence package through
`POST /api/v2/branches/{branch_id}/promotions`.

### Snapshots and trials

`POST /api/v2/worlds/{world_id}/snapshots` accepts an optional `branch_id`, defaulting to the
canonical branch. It requires current world-scoped `run.branch` authority and captures snapshot
contract 2.1 with frozen entity identity, controller and private metadata. The selected branch must
belong to that world. Branch creation uses the exact snapshot ID and seed; retries preserve an
existing trial's progress. Nested trials retain trial-only entities and historical secrets.
Snapshot bodies stay in the private artifact store; public scenes never receive this metadata.

Legacy 2.0 snapshots remain readable for replay. Creating a new trial from one returns
`invalid_operation` with an instruction to capture a new snapshot, because historical entity
metadata cannot be reconstructed safely. Existing persisted trials remain available. These are
projection/entity snapshots; full campaign checkpoint and timeline revision remain unfinished.

### World-scoped reads

Every world-scoped route requires `ADMIN`, or a `DM` or `PLAYER` grant **for that world**. Roles
are never unioned across worlds, so a Player in one world reads nothing of another. Collection
routes (`/api/v2/worlds`, `/api/v2/runs`, `/api/v2/branches`, `/api/v2/snapshots`,
`/api/v2/events`) return only the caller's worlds rather than failing, so a world the caller
cannot read is invisible instead of merely unreadable.

`GET` and `POST /api/v2/actors` require `ADMIN`: an actor carries world capabilities, so minting
one is minting authority.

### Product roles and simulation capabilities

Product roles never *are* kernel capabilities; they are translated into explicit world grants by
`identity.repository.kernel_authority`, which is the single source of truth for both the durable
`sim.actor_capabilities` rows and the in-process authority table.

| Product role | Actor role | Capabilities |
| --- | --- | --- |
| `ADMIN` (global, every world) | `ADMIN` | world read, propose, commit, entity create/control, read secret, faction, divine, branch, evaluate, promote, mind read/write |
| `DM` (per world) | `GM` | the administrator set without `metric.evaluate` and `canonical.promote` |
| `PLAYER` (per world) | `PLAYER` | `world.read`, `action.propose`, `action.commit` |

A Player may therefore speak and act at the table, but holds no `entity.control`, so they can only
act through entities explicitly granted to their actor, and they can never read hidden state,
branch a run, or promote a trial. Granting or revoking a role re-provisions that actor's authority
for the caller's next sign-in.

## Persona and cognition workflow

Persona routes support list/create/generate, immutable version inspection, compilation, and
prompt assembly:

```text
/api/v2/personas
/api/v2/personas/generate
/api/v2/personas/{persona_id}
/api/v2/personas/{persona_id}/versions
/api/v2/personas/{persona_id}/compile
/api/v2/personas/{persona_id}/prompt
```

Generation records schema, generator, ruleset, seed, fixed values, and per-field provenance. A
compiled profile exposes policy weights and starting state without dumping the full schema into a
model prompt.

Cognition routes:

```text
POST /api/v2/cognition/decide
POST /api/v2/events/{event_id}/observe
GET  /api/v2/entities/{entity_id}/mind
POST /api/v2/entities/{entity_id}/relationships
GET  /api/v2/entities/{entity_id}/runtime
PUT  /api/v2/entities/{entity_id}/runtime
```

Observations must derive from visible canonical/trial events. Relationship changes require a
same-world, same-branch source event. A decision returns a trace and proposal; it does not mutate
world state until the proposal enters `/commands`.

For controlled relationship updates, omit `event_type` to derive `conversation` from heard speech
by the target or `attacked` from a perceived damaging attack by that target against the observer.
If supplied, `event_type` must match this fixed classification. Frozen physical grants and masks
govern eligibility; raw event ACLs and caller-authored observation overrides cannot invent evidence.
Unsupported promise/rescue/humiliation classifications are rejected. Only explicit world-scoped
`mind.write.all` callers retain authored subjective overrides with custom deltas/modifiers. Exact
historical retries return their original record without resetting later relationship changes.
Durable updates load current vectors from storage and retain compare-and-set conflict checks.

Mind inspection applies the same server-side world and actor checks in reference and durable
storage. It requires the entity's controller or a world-scoped `mind.read.all`/`mind.write.all`
capability. A browser-supplied actor ID cannot borrow another actor's access.

## Character knowledge

`GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{entity_id}/knowledge` accepts
`query` (at most 400 characters), `limit` (1–20, default 5) and optional `run_id`. It uses the same
authorized trusted context as `/context`, returns `Cache-Control: no-store`, and labels retrieved
items as subjective testimony, experience or recollection rather than canonical truth. Source
card edits do not alter the character's pinned starting claims until an explicit authorized rebind.

Retrieval searches only this body's validated same-branch physical experience and adopted starting
claims. Facts older than the recent 80-observation window remain searchable; arbitrary stored
memory summaries, hidden masks, operator notes, other worlds and other branches never supply text.
Public world lore and a matching global/vector search result do not establish character knowledge.
Reference and durable readers with broad scene inspection but no body control or `mind.read.all`
receive no private experience, memories, card identity or learned lore for another body.

Context reads, retrieval and autonomous proposals share a sensory projection barrier. A pending
source returns the existing `character_context_pending` response (409); retry after the projector
catches up. Retrying the original command can recover reference projection without another event.
The kernel suppresses physical emission and audience resolution for operator/director, evaluation,
checkpoint, correction and protection tags. Such records remain operator audit data.

Context version 1.4, proposal policy 1.4 and dialogue prompt 1.1 record these inputs. Generated
dialogue can retrieve older relevant testimony and cites its original source events in its private
receipt. Model requests contain fiction-only recollection references, never source IDs, controller
metadata or card hashes. Existing immutable proposal receipts retain their original inputs/results.
This boundary does not implement a revised canonical continuation; complete rewind remains section I.

## Population workflow

1. Generate a pool for an explicit world and branch.
2. Check cohort feasibility before a required-strata run.
3. Sample with fixed seeds and record weights/strata.
4. Materialize selected people.
5. Activate only people entering the relevance window.
6. Deactivate to a compressed persistent state when they leave it.

Routes are grouped below `/api/v2/populations`, including `definitions`, `generate`, `sample`,
`cohorts/feasibility`, `materialize`, member activation/deactivation, and transition history.
Lifecycle writes cannot retarget a pool to the currently selected UI world.

## Scenario, run, and calibration workflow

Scenario definitions are immutable `(scenario_id, version)` records. A run chooses an explicit
version or the greatest semantic version, snapshots the base world, creates isolated trial
branches, samples the cohort, executes trials, applies versioned verifiers, and aggregates facts.

```text
GET/POST /api/v2/scenarios
POST     /api/v2/scenarios/{scenario_id}/run
GET      /api/v2/jobs
GET      /api/v2/jobs/{job_id}
POST     /api/v2/jobs/{job_id}/cancel
POST     /api/v2/jobs/{job_id}/retry
GET      /api/v2/trials/{trial_id}
GET      /api/v2/reports
GET      /api/v2/reports/{report_id}
POST     /api/v2/trials/compare
```

Calibration is deliberately two-step:

1. `POST /api/v2/calibration/compare` creates a proposal from synthetic metrics and versioned
   evidence.
2. `POST /api/v2/calibration/{report_id}/review` records `APPROVED` or `REJECTED`.
3. `POST /api/v2/calibration/{report_id}/promote` registers an approved immutable version.

Promotion does not silently reassign any live entity runtime.

## Telemetry and privacy

Telemetry is disabled by default. Settings and capture routes live below `/api/v2/telemetry`.
Capture requires opt-in and a consent version. Sensitive keys are redacted. Export, import,
selective deletion, and retention purge are explicit operations. No external telemetry sink is
configured by this repository.

## Persona purpose

`POST /api/v2/personas` and `POST /api/v2/personas/generate` accept an optional `purpose`:
`CHARACTER` or `SIMULATED_PLAYTESTER` (the default for new identities). Manual successor creation
inherits the existing persona or parent version's purpose when omitted and rejects an explicit
purpose change; use a new identity for a different purpose. For example, generate an identity with
`{"seed": 31, "purpose": "CHARACTER", "fixed": {"risk_tolerance": "LOW"}}`.
Blueprint/detail/version and compile responses include the purpose. Invalid values return `400`
before saving a persona. Compile and prompt routes derive purpose from the stored blueprint;
they do not accept a purpose override. The existing Persona Studio generation form uses the
playtester default; explicit character-purpose selection is currently available through the API.

Character compilation includes core/world traits and excludes player/interface dimensions from
both deep traits and requested prompt traits. It seeds no onboarding goals, GM relationship,
interface capability, or evaluation retrieval filter. Playtester compilation retains existing
evaluation behavior. Purpose does not confer authority, bind a persona to a body, or validate
caller-supplied situation text; those are separate campaign knowledge/control requirements.

## Character context and evaluation boundary

`GET /api/v2/player/characters/{character_id}/history` returns immutable authored-card revisions
for the owner or an administrator. Each has `revision_id`, `revision_number`, `recorded_at`, the
authored `content`, and its existing deterministic `card_version`. Wounds, status, controller/body
association, and timestamps do not create card revisions. Deleting an unbound saved card also
deletes its private authored history; bound history is retained and the card can instead be retired.

An initial Player roster assignment automatically creates a character binding after the existing
typed body-spawn path. Existing bindings survive roster retries and card edits. Old installations
retain their current cards as revision 1; retrying a roster assignment initializes a missing binding.

```text
GET  /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-binding?run_id={run}
POST /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-binding
```

The POST body contains `character_id`, `run_id`, `card_revision_id`, optional `persona_version_id`,
and `replaces_binding_id` (null only for the first binding). The selected card must already be
associated with that world/body. The caller needs body control and `entity.act`, or world-scoped
`mind.write.all`, plus canonical commit/trial proposal authority. Selecting a persona never grants
control. Only `CHARACTER` profiles are accepted. Omitting a persona selects a deterministic
card-seeded baseline; it is not semantic backstory inference or human-history imitation.

Bindings pin the exact compiled persona version/compiler and an immutable card revision, with
composite world/branch/run/body/mind lineage. Replacement uses compare-and-swap: a stale parent
fails; an identical retry returns the original binding without making an old binding current.
Concurrent replacements serialize, and a failed first binding rolls back neutral-mind creation.
Existing memories, beliefs, relationships, goals, and runtime assignments are preserved. Binding
is private controller configuration; it emits no sensory event and changes no canonical projection.
These operations do not make the existing roster/spawn operation atomic (checklist A2).

`GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{entity_id}/context` uses the same
world/viewpoint authorization as the perceived scene. It returns a versioned evidence hash,
projection version, and a model-facing `situation`. Frozen event-time grants and source events
must match the observer/world/branch; operator-tagged events, unbacked beliefs, and memory-summary
overrides cannot add facts. The model-facing situation excludes controller, ledger, and timeline
metadata. Context version `character-context-1.2.0` includes the pinned self-authored identity only
when the caller controls the body or holds `mind.read.all`; broad scene inspection alone does not
grant private identity access. `binding` is operational response metadata outside `situation`.
The situation's `identity` contains fiction and explicitly labeled `starting_knowledge_claims`;
authored claims are not added to observations, beliefs, memories, or canonical truth. Other bodies'
secrets, binding IDs, account/control settings, and persona/compiler IDs never enter that fiction.
Specify `?run_id={run}` when reading a non-default run; multiple live runs require explicit selection.
This endpoint is read-only. `action_candidates` currently contains four typed cardinal
movement attempts when the caller controls this body, holds the command's world-scoped capabilities
(including canonical commit authority), and the perceived self has a position and no known
incapacity. Inspect-only viewpoints return no executable choices. `action_catalog_version` is
`tabletop-character-actions-1.1.0`. Candidates carry typed command parameters outside `situation`;
their action labels contain fiction only. There are no class/species/protagonist restrictions.

These choices are attempts, not guaranteed outcomes. The provider never reads hidden obstacles
or hidden entities to remove choices; otherwise the catalog itself would reveal unknown facts.
The kernel must revalidate authority, lineage, and rules on submission. No model or read request
commits an action. Contextual speech/basic melee are now included as described below; spells,
broader activity catalogs and learned lore remain planned. Durable reads
hydrate fresh canonical and subjective projections. The context read itself does not wait for
dependent observations; trusted proposal generation and the runner enforce that barrier before
choosing an action.

`POST /api/v2/cognition/decide` accepts caller-authored situations/actions only for privileged
`SIMULATED_PLAYTESTER` evaluation (administrator session or automation boundary, still subject to
world/body checks). Its response identifies `mode: EVALUATION` and `committed: false`.
Other browser accounts and `CHARACTER` personas receive `403`. Trusted character proposals
use the server-owned binding and context; the evaluation request cannot invent a binding by
choosing a persona ID. Binding alone does not enable live decisions. Human Game Console commands
continue through their existing kernel path.

### Trusted character proposals

`POST /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-proposals`
accepts only `{"run_id": "{run}", "idempotency_key": "logical-decision-key"}`. Unknown fields,
including situations, actions, personas, runtime configuration, and seeds, are rejected.
The caller must control this body and hold its world-scoped movement/proposal capabilities,
including commit authority on a canonical branch. DM inspection authority alone is insufficient.
New decisions require an active run and an exact version-pinned CHARACTER binding.

The server assembles the same trusted context as the context read, then uses the pinned compiled
persona and perceived action catalog with local deterministic utility policy. Human profiles guide
choices; an explicitly configured provider can express selected speech in free form. This does not
add a narrative planner or full tactical planning.
Before generation, every sensory event with a frozen grant for this body must have its dependent
observation persisted. Otherwise the response is `409 character_context_pending`; retry the same
key after projection catches up. Operator records are outside this barrier and character fiction.

The response contains `authorship: CHARACTER_POLICY`, `execution_mode: PROPOSAL_ONLY`,
`committed: false`, pinned binding metadata, evidence hash, versions, server-derived seed,
and `outcome.proposal`. Operational provenance is outside the model-facing situation. Receipts
contain no context/backstory copy. This is policy-generated evidence, never human preference data.
The same world/branch/run/body/actor/key returns the original receipt, even after world changes,
rebinding, or a durable restart; current body control/capabilities are checked again before retry.
Use a new key for a new decision.

Migration 006 stores each immutable private receipt and decision trace atomically. Requests serialize
on the authorized run and branch; a request-local durable snapshot avoids stale worker caches.
Reference mode serializes proposal reads against command publication. A receipt does not grant
permission to execute later. Submit `outcome.proposal` through `POST /api/v2/commands` to request
normal kernel revalidation and idempotent execution. The proposal endpoint never advances time,
changes runtime assignments, or automatically submits a command. The separate controller/runner
workflow below adds exclusive epochs and bounded scheduling. Broader actions, learned lore, and
speech/combat imitation remain planned.

## Controller handoff and runner

`GET /api/v2/worlds/{world}/branches/{branch}/entities/{body}/control?run_id={run}` reads private
controller status for the body owner or a world-scoped `mind.write.all` operator. An unconfigured
body returns `control: null`; use expected epoch zero for its first handoff.

`POST` to the same path accepts only:

```json
{
  "run_id": "UUID",
  "expected_epoch": 0,
  "mode": "AUTONOMOUS",
  "idempotency_key": "one-logical-handoff",
  "max_steps": 20,
  "interval_ms": 1000
}
```

Modes are HUMAN, AUTONOMOUS, and PAUSED. Handoffs are restricted to canonical LIVE runs. The owner
or authorized operator must hold execution capabilities before enabling autonomy. The action
budget is 1–1,000 and interval is 100–60,000 ms. Each handoff increments the exclusive controller
epoch; a stale expected epoch returns `409 controller_changed`. Retry an uncertain operation with
its original key. The browser rereads current control so an old receipt cannot overwrite later state.

The body retains its human owner, persona, pinned card, and mind. A separate AGENT receives minimal
world capabilities and entity-scoped private context/command grants. Its proposals and ledger rows
carry CHARACTER_POLICY authorship, controller epoch, step, and decision-trace/pinned-identity
attribution. They are not human preference evidence. Handoffs have private append-only receipts,
never emit sensory events, and do not change the character context hash.

Every new managed command must carry the epoch observed by its controller. The typed console
adapter sends `control_epoch`; autonomous commands also carry `control_step`. The server never
upgrades a delayed command by stamping a fresh epoch. Unmanaged legacy bodies retain their
existing behavior. Kernel fencing occurs inside the same branch/state lock as canonical mutation.
Old controllers cannot act after takeover; committed retries cannot advance the world or step twice.

`python main.py runner` processes due autonomous controllers using trusted pinned context and
local utility candidates and optional configured speech generation, then submits through the kernel.
No browser cookie is used. Canonical commit and budget advance share one database transaction.
Epoch/step proposal keys survive crashes and concurrent workers. Observations still flow through
the frozen perception outbox; the next decision waits for them. Invalid actions pause with
`action_failed`; pending observations defer every 250 ms and pause after 40 unsuccessful checks.
The budget pauses with `step_limit`. Resume explicitly with a new handoff/key/current epoch.

The Game Console exposes Let character act, Pause autonomy, Take control, and an action limit.
It polls status, refreshes the authorized scene on progress, and disables human submission until
takeover. Saved mode survives browser closure and process restart. Closing a browser while HUMAN
does not enable autonomy. Presence timeouts/reconnect policies, broader human-history inference, richer
actions, narrative goals, and the canonical world clock remain separate work; due times here are
operational wall-clock scheduling only.

Runtime GET reads durable assignments fresh and adds controller metadata for managed bodies.
Handoff atomically selects HUMAN or UTILITY while preserving runtime configuration. Legacy runtime
PUT cannot bypass explicit handoff for a managed body.

## Movement behavior profiles

`GET /api/v2/worlds/{world}/branches/{branch}/entities/{body}/behavior-profile?run_id={run}`
is a private, read-only, no-store inspection for the body controller or a world-scoped mind reader.
It returns a content-addressed `profile_id`, policy version, exact player/character/binding scope,
matching source-event IDs, sample count, confidence, direction scores and reviewable contradictions.
Generated proposal receipts freeze this same profile under `behavior`; an exact proposal retry
returns its original profile even after further human actions. Profile metadata never enters
character-context `situation`, speech, memories or sensory events.

Migration 008 stores only new accepted, untraced HUMAN_INPUT cardinal movement in canonical LIVE
runs, through the bound body's human owner. Server-derived `input_origin` distinguishes manual
input, submitted policy advice, and operator automation independently from controller authority.
Client origin labels cannot authorize training. Historical commands remain UNSPECIFIED and are
not backfilled as human evidence. Direct kernel callers must explicitly supply trusted input origin.

The kernel captures its locked pre-command perceived spatial features, offered movement attempts,
chosen direction and binding. Evidence insertion shares the command/event/outbox transaction.
Rollback and duplicate submissions cannot create partial or repeated preference evidence. Neither
hidden obstacles nor other characters' secrets are used to filter or score options.
If subjective observations are pending during a human command, it can still commit and record
physical movement evidence. Speech and combat choice evidence require the complete context.
Character policy proposals wait for the pending observations.

The current policy compares the latest 256 samples in this exact world/branch/run/body/player/
character. It matches perceived zone, injury, company count, relative quadrants and distance buckets.
Confidence is `matching_samples / (matching_samples + 3)`. Comparable demonstrated direction
frequencies guide movement; current persona curiosity/risk weights supply approach/avoid behavior,
with fallback influence reduced as comparable human evidence gains confidence.
The pinned card's backstory, motives and values also supply a bounded English tendency vocabulary:
cautious/caution/careful/avoid/survive/survival versus curious/curiosity/explore/exploration/discover/
discovery/sociable. This is explicit rule-based inference, not general semantic understanding.
Card secrets and starting lore do not become behavioral instructions. Repeated opposing human
movement creates a private conflict notice for card/history review. All four actions remain typed
attempts; every chosen action still passes the kernel's current authorization and collision checks.

Other branches, runs, players, bodies and characters are excluded. Full rewind/promotion evidence
restoration, negative/rejected-choice learning, unrestricted dialogue, relationships, tactical plans and broad
backstory interpretation remain checklist work. No new provider credential is required.

## Speech and combat choice profiles

The trusted catalog adds fact-free GREET, ASK, DEESCALATE and ASSERT templates at WHISPER, NORMAL,
LOUD or SHOUT volume when a perceived conversational turn or attack has not yet been answered.
After the character replies, it cannot answer itself indefinitely. This is intent/volume selection,
not free-form dialogue generation or verbatim imitation. The default language is common.

A validated observation of an attack against this body identifies known threats. Only currently
visible, apparently capable threats within one grid step become basic melee candidates (up to
eight). Four movement attempts remain available for advance, maneuver or withdrawal; the normal
kernel checks reach, health, authority and current controller epoch on submission. Hidden armor,
unseen targets and private state never rank candidates. No spell or damage build is inferred.
Known threats currently persist while visible/capable; richer ceasefire/relationship/goal policies
remain planned. Normal dialogue or mere presence does not authorize an autonomous attack.

`GET /api/v2/worlds/{world}/branches/{branch}/entities/{body}/choice-profile?run_id={run}` is a
private no-store inspection with the same body/mind authorization as behavior-profile. It returns
version `speech-combat-behavior-1.0.0`, confidence, matching source IDs, per-candidate scores and
conflicts. Receipts freeze this profile separately under `choices`; legacy `behavior` hashes and
receipts stay readable. Speech/combat matching includes perceived layout, injury, company, threat
count and conversation readiness. Calm movement keeps its existing policy; active conversation
and combat use contextual choice scores instead of unrelated calm-direction habits.

Migration 009 records new accepted human replies, known-threat basic attacks and contextual
movement choices atomically with their canonical source event. Speech preferences store only
classified intent and volume, never utterance text or claims. An explicit bounded English classifier
recognizes greeting/question/de-escalation/assertion cues. Compiled risk/conflict/social/directness
traits and pinned peaceful/aggressive card tendencies provide fallbacks; repeated demonstrated
choices gain influence with confidence. These are reproducible rules, not general language
understanding. Historical unknown/pre-catalog context is not reconstructed or backfilled.

Combat commands now emit physical sight/sound observations. Event-time subject visibility masks
participant IDs; hit/damage require inspected sight of both participants. Sound-only witnesses
receive an anonymous disturbance, including behind walls or when participants are invisible.
Character context validates their frozen grants before using them. Eligible observations follow
canonical source-event order before taking the bounded window, even when timestamps tie.
Operator/profile/handoff metadata is kept
outside sensory fiction, character prompts and speech. Full tactical plans, learned arbitrary
phrasing, spell selection, narrative planning and complete timeline restoration remain open.

## Generated dialogue and tactical choices

Context `character-context-1.6.0` includes the body's own mana/reach/learned spell IDs and inspected
guard stance. Other bodies' mana/reach/spell knowledge stay hidden. Catalog
`tabletop-character-actions-1.3.0` and proposal policy `character-proposal-policy-1.4.0` offer:

- `tabletop.combat.guard` takes `{}`. A capable unguarded body gains two armor against the next
  physical attack; that attempt consumes the guard, including a miss. Guards do not stack.
- `tabletop.combat.attack` takes only `target_id`. Rules `tabletop-action-rules-1.2.0` resolve
  UNARMED/SHORTSWORD (1d6, reach one) or an owned SPEAR (1d8, reach two), ability/training bonuses,
  and poisoned/frightened disadvantage. Legacy unarmed body reach remains supported. A living,
  awake, capable attacker needs a different visible, living target within the same zone/reach.
  Caller bonuses/dice are rejected. Logical action seeds and configured-clock readiness are
  allocated by the kernel; clocked initiative, conditions and death/recovery use the shared policies
  described above. Legacy scoreless bodies retain their explicit flat profile until configured.
  Selling the final equipped weapon copy atomically switches the seller to UNARMED. Legacy
  unavailable equipment keeps scene/context reads available and suppresses impossible melee
  candidates; the attack handler still rejects an unavailable loadout.
- `tabletop.magic.invoke` and `tabletop.magic.cast` take only `spell_id` and `target_id`.
  ARCANE_BOLT costs two mana,
  deals three damage and reaches six grid steps. MEND costs two mana, heals four up to maximum
  health and reaches two steps. Both require a capable caster and current same-zone visible living
  targets; MEND can rescue a 0-HP body and ordinary spells cannot resurrect a dead one. Callers
  cannot supply power, cost, range or extra fields. The caster must have learned the registered
  spell; an explicit empty `known_spells` list permits none. Legacy bodies without that field and
  new cards that omit it retain both starter spells. There is no class/protagonist gate.
- Autonomy offers damaging spells only against perceived attackers, MEND for its own wounds,
  and guard in threat situations. Injury favors healing/withdrawal; range, wounds, demonstrated
  choices and persona/card tendencies influence priority. All execution rechecks live state.

The console accepts `/guard`, `/invoke ARCANE_BOLT|MEND <perceived target name or id>`
and the same `/cast` syntax. Merge and deploy this compiled bundle together with the 2.0.0 API;
the preceding console's arbitrary `/cast` syntax is rejected by the new API. New roster-spawned
bodies validate optional nonnegative `character.sheet.mana` (default zero) and registered
`character.sheet.known_spells` before roster mutation. Later card edits and roster retries do not
refill resources or teach a running body spells. Old committed requests return their original
scoped receipt even if they contain retired parameters; new requests must use contract 2.0.0.
Choice version `speech-combat-behavior-1.1.0` and migration 010 extend guard/spell history while
retaining old 1.0.0 evidence and frozen profiles. Ally strategy, resurrection, broader spell and
loadout systems, ceasefires and full tactical planning remain open.

To generate free-form utterances, set `TTDM_DIALOGUE_MODE=openai-compatible`, explicitly choose
`TTDM_DIALOGUE_BASE_URL` (API base ending in `/v1`) and `TTDM_DIALOGUE_MODEL`, and provide
`TTDM_DIALOGUE_API_KEY` only if that endpoint needs bearer authentication. Defaults are off/blank:
no endpoint, model or key is chosen. Restart API and runner with matching configuration.

The adapter calls `/chat/completions` with bounded messages/output and JSON mode. It accepts only
spoken text and known experience references. Model output cannot choose a command, target,
effect, volume, language, claims or deltas. History/persona first select intent and volume;
generation expresses the choice from sanitized identity, motives, values, authorized experience
and recollections. Private card secrets, hidden world state and account/control/profile/ledger
IDs are excluded. The latest incoming speech reference must support the reply. Explicit
metafiction/UUIDs, repeated utterances, stage directions, extra fields, unknown sources, incomplete
responses and network failures use the bounded template fallback. This is not a semantic proof of
every sentence: generated text remains fallible testimony and creates no automatic belief claims
or canonical facts beyond the act of speaking.

Private receipts add `dialogue.status` (GENERATED/FALLBACK), source-event references, output hash,
configured model and prompt version `character-dialogue-1.0.0`. They store no endpoint/key or full
prompt. Exact retries/restart return the frozen receipt without another HTTP call. Synthetic
speech never trains human evidence. Outages do not retry within a decision; request a new key
after recovery for fresh generation. Existing budgets, projection barriers and epoch fences apply.
Generation is serialized within proposal creation and bounded by timeout; slow providers can delay
other work on that branch.

Compatibility settings are `TTDM_DIALOGUE_TOKEN_PARAMETER=max_tokens|max_completion_tokens`,
`TTDM_DIALOGUE_JSON_MODE=0|1`, `TTDM_DIALOGUE_SEND_SEED=0|1`,
`TTDM_DIALOGUE_RUNTIME_KIND=LOCAL_LLM|HOSTED_LLM`, `TTDM_DIALOGUE_TIMEOUT` (0–30 seconds, exclusive
of zero), and `TTDM_DIALOGUE_MAX_TOKENS` (32–1024). Defaults are in [.env.example](../.env.example).
The endpoint must support the selected options; see the [official Chat Completions contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Model outputs are not promised bitwise deterministic even with seeds; saved proposals/events retain
the accepted utterance for replay. Spontaneous conversations and narrative/world planning remain open.

## World time and offscreen activities

The durable world runner supplies a lease token to `tabletop.clock.tick`. The assigned executor
can submit a due tick without a token while no worker holds an active lease. A previous token
cannot authorize new work after reassignment, expiry or completion. A committed idempotency key
returns its original receipt. Clock configuration creates or cancels the pending step together
with changes to the clock. Trial clocks stay isolated from the canonical worker.

World time is an integer number of simulated seconds per branch. New worlds have no running
clock. Configure one explicitly, initially paused. Clock state, pending weather and current
activities live in the existing canonical projection: the normal kernel transaction commits
progress, physical effects, receipt, event and outbox together. Clock storage uses existing tables;
the population binding workflow below adds migration 011.

Setup uses the existing authenticated JSON APIs:

1. An administrator creates an actor with `POST /api/v2/actors`: `kind: AGENT`, an explicit
   `world_id`, and only `world.read`, `action.propose`, `action.commit` capabilities. No browser
   account or cookie is reused by the worker. The executor must have these grants in this world.
2. Submit `tabletop.clock.configure` through `POST /api/v2/commands`, with world/branch/run IDs,
   a new `idempotency_key` and these parameters:

   ```json
   {
     "expected_epoch": 0,
     "executor_actor_id": "the-agent-uuid",
     "paused": true,
     "seconds_per_tick": 1,
     "offline_policy": "FREEZE",
     "max_catch_up_ticks": 10,
     "until_seconds": null,
     "wall_time": "current-time-in-UTC-with-offset"
   }
   ```

3. Submit `tabletop.activity.start` with `entity_id`, `kind: WEED` or `REST`, and
   `duration_seconds` (1–86,400; default 3,600). The body must exist and be capable. One current
   activity per body prevents parallel duplicate output. Replacement requires completion/cancel.
4. Optionally submit `tabletop.weather.schedule` with `zone_id`, `due_seconds` and `raining`.
   The zone must exist (`world` is the default zone); past scheduling is rejected. Equal-time
   schedules follow insertion order, with a stable identifier tie-break. `tabletop.weather.cancel`
   takes `schedule_id` while it is pending.
5. Reconfigure using `expected_epoch: 1`, the same executor, current UTC and `paused: false`.
   Every reconfiguration increments the epoch, preserves simulated time/work and resets the next
   operational tick. Optional `until_seconds` stops exactly at a future simulated boundary.
6. Start `uv run tabletop-dm world-runner`; managed Compose startup includes that service.
   It only drives explicitly enabled canonical LIVE clocks. Multiple processes can share the
   assigned executor; the branch lock, epoch/step and one logical retry key commit each step once.

Clock/activity/weather management requires world `entity.control` authority plus normal command
capabilities. Players cannot advance time, schedule rain, or inspect pending offscreen work.
`GET /api/v2/worlds/{world_id}/branches/{branch_id}/clock` returns current clock, activities,
weather and pending weather to authorized world managers from a fresh durable snapshot. It does
not claim worker liveness. All new commands are discoverable in `/api/v2/commands/contracts`.
Whole-branch replay also requires `world.read.all`; a Player world role alone cannot read raw
projections, pending work or clock control metadata through that inspection route.
Clock inspection and replay use fresh durable snapshots and `Cache-Control: no-store`, including
when another worker advanced the branch after this API process started.

One operational UTC second makes a tick due. `seconds_per_tick` (1–3,600) controls how many
simulated seconds that tick advances. FREEZE discards missed operational ticks, including downtime;
it advances once and schedules the next tick after the supplied current UTC. CATCH_UP processes
missed ticks in order, at most `max_catch_up_ticks` (1–60) per command; subsequent polls continue
catch-up. Wall-clock UTC is recorded operational input, never substituted for simulated time.
Reconfiguration resets that operational boundary, so paused time is not later caught up.

Pause using a new configure command with the current epoch and `paused: true`. A configured clock
pause also suspends unattended character runners without spending their failure budget. The kernel
fences captured character proposals at commit. Worlds without clocks retain their previous behavior.
The typed `WorldClockPaused` rejection is an expected suspension, including pauses during model
generation; it preserves controller mode, step and failure budget so resume needs no new handoff.
Human/operator commands remain explicit instantaneous actions. Action duration, initiative and
scaling character cooldowns with simulated speed remain C3 work. The character observation barrier
continues to apply; clock/configuration events emit no fictional observations.

For deterministic stepping, `tabletop.clock.advance` requires a paused clock, `expected_epoch`,
`expected_seconds` and `to_seconds`; it moves forward at most one simulated day. Clock and weather
boundaries are processed in stable order. Advance is available on isolated trial branches after
explicit configuration for that trial run; the background worker never drives trials.

WEED accrues one abstract `weeded_units` counter per working simulated second on the canonical
body. REST reduces its existing `fatigue` by one per second, capped at zero. Work stops at its
duration. Rain pauses WEED only; incapacity or moving away pauses either activity. Waiting work
resumes when its physical conditions clear. `tabletop.activity.cancel` requires both `entity_id`
and the current `activity_id`, protecting a replacement job from stale cancellation. Current rows
are replaced only by a new authorized start; prior transitions remain in the append-only ledger.
The initial limits are 256 activity bodies and 128 pending weather changes per branch.

Progress depends on elapsed simulated time, never camera visibility. Rain starting and stopping
inside a large advance splits work at those exact boundaries. Returning players receive only an
inspected body's current kind/status/progress and visible work output through the existing scene;
hidden bodies and pending schedules stay hidden. The console renders that activity on entity rows.
Visible-tab polling, reconnect and post-action scene refresh load it across clients.
Context is `character-context-1.3.0`; operator clock epochs, UTC, executor IDs,
schedule/activity IDs and control metadata stay outside character fiction.

This is a bounded activity/time foundation. General leased arbitrary due-work queues, population
activation/deactivation reconciliation, persistent hunger/routines, travel/sleep/consumption,
automatic detailed activity selection, weather narration and complete timeline restoration remain
open checklist work. Existing `PopulationLifecycle` records do not create a second worker/resource
balance and are not automatically attached to this first activity vocabulary.

## Population binding and NPC routines

Population generation/materialization and the new binding convenience route retain the existing
global-admin gate. Typed population and routine commands require world-scoped `entity.control`,
`action.propose` and canonical commit authority. Players cannot inspect private population state.

1. Configure a branch clock and its explicitly granted AGENT executor using the world-time workflow.
2. Generate a population and materialize the desired members with the existing population routes.
3. Create or choose an existing canonical body using normal entity commands. Set its actual health,
   inventory and location deliberately. Source population finances never replace body resources.
4. Bind once with
   `POST /api/v2/populations/{population_id}/members/{persona_id}/bind`:

   ```json
   {
     "entity_id": "<existing body UUID>",
     "run_id": "<clock's live run UUID>",
     "expected_source_version": 1,
     "idempotency_key": "bind-gardener-1"
   }
   ```

   The server reads the source; the command transaction locks and verifies its version and full
   hash. Population identity is provenance, separate from the body's pinned CHARACTER persona,
   authored card and mind. Bodies and population identities each bind once in a branch. Binding
   is canonical-only; trial snapshots inherit their own branch-local live metadata.
   Consequence promotion can carry live lifecycle changes but cannot create, erase or rebind
   a source identity. Rewinding to before embodiment requires a future timeline/import workflow.
5. Submit `tabletop.routine.configure` through `POST /api/v2/commands` with parameters:

   ```json
   {
     "entity_id": "<bound body UUID>",
     "expected_version": 0,
     "enabled": true,
     "work_seconds": 1800,
     "rest_seconds": 600,
     "meal_seconds": 5,
     "fatigue_limit": 3600,
     "hunger_limit": 14400,
     "relevance_radius": 12,
     "relevance_anchors": []
   }
   ```

   Work/rest periods are 60–86400 seconds; meals are 5–3600 seconds. Initial version is zero;
   subsequent configuration requires the current version and deliberately replaces the routine.
   Cancel any manual activity first. Disable the routine before starting/cancelling manual work.
   Up to 32 routines and 256 bound members are supported per branch.
6. Resume the clock and run `world-runner`, or use paused manual clock advances. No browser is
   required. WEED produces one `weeded_units` and one fatigue per working second; REST removes
   one fatigue per second. Hunger grows one per living routine second. EAT consumes exactly one
   `inventory.food` on completion and relieves 14400 hunger. Missing food waits with `NO_FOOD`;
   authorized replenishment resumes the same partial meal. Routines do not create free food or
   import archived finances. Rain, displacement and incapacitation preserve partial work.

`GET /api/v2/worlds/{world_id}/branches/{branch_id}/population` is a fresh, `no-store`, world-manager
inspection of bindings, routines and canonical transitions. Existing population member, counts,
activation/deactivation, bulk activation and transition routes read the canonical bound member.
Bound legacy transitions reject replacement state, use simulated time rather than client
`world_step`, and set an explicit relevance override. Use `tabletop.population.level` with
`persona_id`, `expected_version`, `level` and `relevance: "AUTO"` to restore automatic relevance.

Automatic relevance uses capable same-zone bodies within the configured 3D radius. Explicit
anchors may be any existing body; empty anchors use other physically embodied controllers.
Relevance changes are reconciled at the start of elapsed time, using the current simulated instant;
tick size and unrelated weather boundaries do not move their transition timestamps.
Human connection and camera state are absent from the calculation. ACTIVE/MATERIALIZED changes
use `PopulationLifecycle`, preserve mental metadata, and never recreate a body or reset its job.
Both representations run the same coarse physical routine. Characters only see inspected physical
activity; pool IDs, lifecycle levels, schedules and private source cognition stay operator-side.

The initial vocabulary now includes gardening, rest, meals, local travel, daily sleep and social
attendance. Wages, tactical danger responses and a general activity planner remain incomplete.
Health at or below zero stops work; hunger drives meals without applying starvation damage.

## Travel, sleep and social obligations

Add an optional `life` field to `tabletop.routine.configure`, using its current `expected_version`:

```json
{
  "entity_id": "<bound body UUID>",
  "expected_version": 1,
  "life": {
    "home": {"x": 3, "y": 0, "z": 0, "zone_id": "world"},
    "workplace": {"x": 1, "y": 0, "z": 0, "zone_id": "world"},
    "step_seconds": 60,
    "sleep_start_seconds": 79200,
    "sleep_seconds": 28800,
    "danger_quiet_seconds": 300
  }
}
```

This replaces the configured routine; omitted fields use the normal routine defaults. Omit `life`
or set it to `null` to return to work/rest/meals. The day is 86400 simulated seconds; the example
sleeps from 22:00 until 06:00, including across midnight. At initial simulated time zero it is
already the previous night's sleep window. A sleeper first travels home, so late arrival reduces
actual sleep before the fixed wake time. Sleep removes two fatigue per actual sleeping second.

Travel takes 1–300 seconds per cardinal grid step, stays in the body's current zone/elevation and
uses the same collision rules as manual movement. Home/work destinations must be unblocked at
configuration. Routing searches at most 4096 nodes and 256 steps; it waits with `PATH_BLOCKED`
when no route fits that bound and can reroute unfinished travel if obstacles change. Actual
position and traversed steps persist. Manual displacement pauses with `MOVED`, preserving work;
return to the expected location or explicitly reconfigure. This does not implement portals or
general cross-zone navigation. Hunger still uses the body's finite inventory.

Sleep normally takes priority over appointments; hunger takes priority during waking time. A
drop in the body's health wakes/interrupts it until the configured quiet interval passes. Zero
health stops progress. An accepted human action can wake its own sleeping body; rejected actions
do not. Actual damaging attacks also wake sleepers immediately. Sleepers receive no ordinary
sight/sound observations; waking actions freeze perception against their event-time post-state,
and waking later never reveals old events. The character runner and captured policy submissions
wait without spending controller steps while asleep, then may resume when awake. No class, faction
or protagonist restriction applies.

Schedule a commitment with `tabletop.obligation.schedule` through the normal command endpoint:

```json
{
  "participants": ["<body UUID>", "<other body UUID>"],
  "place": {"x": 3, "y": 0, "z": 0, "zone_id": "world"},
  "starts_seconds": 43200,
  "duration_seconds": 300,
  "grace_seconds": 300,
  "lead_seconds": 300,
  "repeat_seconds": 86400,
  "wake_for_obligation": false,
  "radius": 1
}
```

Participants are 2–8 unique existing bodies. Life-plan participants depart at start minus lead time;
others can attend if already present, without being moved or having their activities replaced.
Everyone must be capable, awake and within the physical radius in the same zone/elevation. Progress
only accrues jointly after the scheduled start. A meeting can start through start plus grace, but
must complete by start plus grace plus duration; an unavailable partner or competing need can
interrupt it or cause a miss. Sleep wins unless `wake_for_obligation` is explicitly true. Attendance
does not fabricate speech, memories or relationship changes.

Starts must be within seven simulated days. Optional repetition is 600–604800 seconds, with enough
space for the entire attendance/lead window; overlapping participant commitments are rejected,
including future repeating conflicts. Up to 128 obligation records are supported per branch.
Each recurring record retains occurrence, progress, completion/miss counters and its latest outcome.
`tabletop.obligation.cancel` accepts `obligation_id` and `expected_occurrence`; it stops future
attendance/recurrence and lets the body resume its previous work or commute.

The privileged population inspection now includes `obligations`. Character scenes/context only
show inspected physical activity and actual positions; destination, route, appointment IDs, sleep
schedule, and private phase/attendance state are excluded. New activity progress is qualitative,
so the console does not reveal how far an NPC is from a private future goal. The existing worker,
pause/downtime policy, atomicity, idempotency and trial isolation remain in force. No SQL migration
after 011 or additional service/provider is required. Detailed travel observations, tactical
responses, motive-driven planning and full timeline correction remain separate checklist work.

## Daily goal planning

Add optional `planning` inside a routine's `life` configuration, replacing the routine with its
current `expected_version` as usual. Existing life plans without this field retain their behavior.

```json
{
  "planning": {
    "retry_seconds": 300,
    "goals": [
      {
        "goal_id": "garden",
        "kind": "WEED",
        "place": {"x": 1, "y": 0},
        "seconds_per_day": 14400,
        "priority": 80
      },
      {
        "goal_id": "reading",
        "kind": "REST",
        "place": {"x": 3, "y": 0},
        "seconds_per_day": 1800,
        "priority": 20
      }
    ]
  }
}
```

This is the nested `planning` value, not a standalone command. Configure 1–8 unique lowercase
goal IDs (letters, digits and underscores; start with a letter, at most 40 characters), WEED or
REST kinds, local same-elevation destinations, daily durations of 1–86400 seconds, priorities
1–100 and a 10–3600 second retry interval. These are intentions, not guaranteed outcomes. The
planner selects the highest-priority feasible goal, then shorter Manhattan distance and goal ID;
it commits to that goal until completion or a causal interruption. Different priorities can produce
different daily choices without inventing an occupation, personality or knowledge for a body.

Own injury/manual wake triggers the existing quiet interval: the NPC seeks its configured home
and rests before returning to daily activity. Otherwise sleep, hunger with real carried food,
fatigue recovery, and due appointments precede discretionary goals. Rain prevents gardening;
other feasible goals remain available. With no feasible goal, or hunger without food, the NPC
heads home and rests. This does not generate food, heal injuries, find hidden attackers or
automatically buy supplies. Actual replenishment lets meals resume on the next clock command.

Blocked goals are reconsidered on fixed simulated-time retry boundaries; feasible alternatives
can run meanwhile. Retry boundaries preserve unfinished homeward steps even when retries are
shorter than a movement step, including across restart. Manual displacement causes a fresh physical route back to the selected goal,
preserving partial work instead of requiring reconfiguration. Home can also be unreachable, in
which case travel waits with `PATH_BLOCKED`. Existing local path bounds and collision rules apply.
Social attendance still requires real awake participants and may be missed during competing needs.

Only actual WEED/REST time at a goal counts against its daily quota. Travel, meals, emergency
recovery and interruptions do not fulfill it. At midnight the bounded daily counters reset;
canonical health, food, position, lifetime work and unfinished needs remain on the same body.
Daily goals do not accumulate a backlog or unlimited history. Disabling or replacing the routine
deliberately resets its intentions, as with earlier routine configuration.

Private population inspection includes `routines[body].planner`: policy version, current day,
per-goal elapsed time, last choice/reason and decision sequence. These records and goal IDs,
priorities and quotas never enter the player scene or character context. The console continues
showing inspected physical work, rest, sleep and travel using existing activity labels.

Policy `npc-daily-planning-1.1.0` runs inside `npc-routines-1.3.0` and the existing authorized clock
transaction; projection, effects, command/event/outbox, retries and replay remain atomic. No new
migration, worker, provider or port is required. Without optional motivation below, this bounded
physical planner uses authored priorities. It does not create dialogue/relationships, choose tactical combat
responses or implement the remaining detailed cognition/scene-action planning in E3/F.

## Belief and persona driven NPC goals

Daily planning can additionally rank its finite goal menu using the NPC's pinned identity and
own perceived evidence. This is opt-in: set `life.planning.motivated` to `true`. Existing routines
retain their authored priorities when this flag is absent. No model provider is required.

Set up an existing canonical NPC body as follows:

1. Create a saved character card through the existing character API with the intended identity
   and backstory. As the world's DM/Admin, send PUT to
   `/api/v2/dm/worlds/{world}/branches/{branch}/entities/{entity}/character-card` with
   `{"character_id":"<saved-card UUID>"}`. It requires `entity.control` and `mind.write.all`.
   A non-admin DM must also own the selected card or have it already assigned to this world;
   destination-world authority does not permit taking another user's private unassigned card.
   The repository checks this against the locked card before association or returning its content.
   A card/body association cannot move to a different body or replace another card. Retrying the
   same association returns the saved record. It creates no account, roster seat, body or resources.
2. Compile and pin a CHARACTER persona through the existing `character-binding` endpoint,
   including the card revision. Keep the population source/body binding as its separate setup step.
3. Configure a life plan and daily goals through the normal versioned routine command. Each goal
   may declare `"motive":"DUTY"`, `"CURIOSITY"`, `"CARE"` or `"RECOVERY"`. Defaults are DUTY for
   WEED and RECOVERY for REST. Set `"motivated":true` alongside the planning goals/retry interval.
4. Grant the configured clock executor world-scoped `mind.read.all` explicitly, in addition to
   its existing clock capabilities. An actor controlling the particular body with `entity.act`
   may read its own mind instead. Keep the perception projector running: an unprojected experience,
   unavailable pin, or missing grant rejects the clock command atomically rather than guessing.

Policy `npc-goal-motivation-1.0.0` adds LOW/MEDIUM/HIGH trait weights of -20/0/+20 per trait to
authored priorities: DUTY uses conscientiousness/achievement priority, CURIOSITY curiosity/openness,
CARE agreeableness/community loyalty, and RECOVERY security priority/patience. Need, sleep and
appointment constraints still precede discretionary goals. A changed relevant belief may interrupt
a committed goal while retaining its actual partial work and daily fulfillment.

Two structured claim forms from normal perceived events currently influence motivation:

- `subject_type: "entity"`, `subject_id: <this NPC body>`, `predicate: "motive_importance"`,
  `value: {"motive":"CARE","importance":80}` adjusts that motive by confidence times the signed
  integer importance (-100 through 100). It expresses subjective importance, not canonical fact.
- `subject_type: "place"`, `predicate: "place_danger"`,
  `value: {"place":<normal local Place object>,"dangerous":true}` can exclude goals at that place.
  LOW/MEDIUM/HIGH risk tolerance requires confidence at least 0.25/0.5/0.75. A later matching
  non-danger belief can reopen it; a believed-unsafe home is not used as a fallback destination.

The claim must match an active belief of this NPC and its frozen source observation. Confidence
cannot exceed source/claim confidence. Unheard, foreign, malformed, contradicted and unsourced
inputs are ignored. Active motivation retains its validated source evidence even after more than
80 newer unrelated events; the model-facing recent-experience window remains bounded at 80.
Existing belief revision keeps the latest active value for each subject and
predicate; it does not store simultaneous importance values for different motives on one subject.
This policy does not interpret arbitrary prose into beliefs or invent new occupations/goals.

Manager inspection exposes private motivation provenance and chosen goals. Player scenes expose
only physical activity/progress. Choice inputs and effects commit together; replay and exact retry
use the original frozen inputs even if later beliefs differ. Trials still require their own valid
scope/pin and remain isolated. Motivation reuses schema 011; snapshot identity additionally
requires migration 012. No new UI form or provider is enabled.

## Error contract

Errors use a JSON body with a stable `error` code and, where safe, a human-readable detail.
Common status meanings:

- `400`: invalid input, invariant violation, or invalid lifecycle transition;
- `401`: no valid browser session or automation token;
- `403`: password change required, missing role/capability, invisible evidence, or disallowed
  branch operation;
- `404`: resource is absent or not visible to the caller;
- `409 character_context_pending`: retry character advice after subjective projection catches up;
- `409 controller_changed`: reload control before making a new logical handoff;
- `409`: idempotency, uniqueness, version, or state-hash conflict;
- `503`: configured dependencies or migrations are not ready.
