# Spatial epistemics

TableTop DM enforces knowledge boundaries from embodied location. Movement is therefore not only
a coordinate update: it changes which future events a character can perceive.

```text
canonical command -> deterministic state transition -> event emission
                  -> event-time spatial resolution -> PerceptionGrant
                  -> subjective observation -> belief evidence -> optional memory
                  -> entity-scoped scene read model
```

The constitutional rule is:

> Canonical state is global. Knowledge is local. Location affects perception. Perception creates
> observations. Characters reason only from information they possess.

## Boundaries

These records deliberately mean different things:

| Record | Meaning |
| --- | --- |
| `EventEnvelopeV2.visible_to` | actors allowed to retrieve the raw canonical event |
| `sim.event_perceptions` | embodied entities that directly or partially perceived the event |
| `cognition.observations` | masked subjective payload perceived by one entity |
| `cognition.belief_evidence` | append-only evidence and testimony provenance for a belief |
| `cognition.memories` | selectively consolidated recollections linked to an observation |
| `PerceivedScene` | current player-facing view, never a canonical entity projection |

Physical witnesses are never added to `visible_to` merely because they heard or saw something.
They receive an observation derived from a frozen `PerceptionGrant`; this prevents a partial
witness from downloading unmasked canonical payload.

`observed_by` remains a compatibility summary of unique controller actors. Cognition does not use
it as its gate because one actor may control several bodies in different locations.

## Embodiment authority

`entity.act` permits an actor to act through an entity already assigned to it. Commands such as
movement, attack, casting, interaction, battlefield control, and in-world speech also declare
`requires_controlled_entity=True`; possession of the capability alone does not grant control of
another body.

`entity.control` is administrative authority for creation, assignment, transfer, or override.
Player role grants include `entity.act` but not world-wide `entity.control`. When a DM assigns a
portal character to a player membership, the character is linked to a kernel embodied entity and
that entity is added to the player's world-scoped controlled set.

## Shared event materialization

Reference and PostgreSQL execution call the same `EventFactory`. Each command definition may
provide an `emission_builder` that receives pre-command and post-command working states. The
factory resolves a stable event ID and produces:

```text
EventMaterialization
├── canonical EventEnvelopeV2
└── zero or more entity-scoped PerceptionGrant records
```

PostgreSQL commits the projection, command, event, perception grants, and outbox record in one
transaction. A retry returns the original receipt and grants. Reference mode publishes its copied
state only after the same materialization succeeds.

The `tabletop-dm projector` service claims world-event outbox records with `SKIP LOCKED`, projects
their frozen grants, and marks the record published only after every subjective write succeeds.
Partial processing and crashes are safe because observation, evidence, and memory IDs are stable
and inserts are idempotent. The API also projects synchronously for immediate local feedback, and
startup catch-up repairs any gap before the projector resumes.

Every grant stores the resolver version and a SHA-256 hash over the relevant event-time state,
including before/after hashes, emission, positions, zones, portals, occluders, sensory profiles,
and environmental conditions. Moving into range later never changes the frozen audience.

## Grid spatial model

The first resolver is intentionally deterministic and small:

- `tabletop.spatial.positions`: entity, zone, integer coordinates, elevation, and facing;
- `tabletop.spatial.zones`: name, ambient light, and ambient noise;
- `tabletop.spatial.portals`: connected zones, open/closed/locked state, sight/sound transmission,
  and movement allowance;
- `tabletop.spatial.occluders`: grid obstacles with sight opacity and sound attenuation;
- `tabletop.sensory_profiles`: acuity and blinded/deafened/invisible conditions.

Sight uses same-zone range plus deterministic grid supercover line-of-sight. Sound uses distance,
ambient noise, portal transmission, and occluder attenuation. There are no random perception rolls
in this slice. Future stealth or concealment checks must be seeded and versioned.

The resolver implements a kernel protocol. A browser, Unreal, or Unity adapter may later provide
richer spatial facts while preserving the same event, grant, cognition, and scene contracts.

## Speech and testimony

`tabletop.console.submit` is out-of-character interface text and emits no sound.
`tabletop.dialogue.speak` is embodied speech; it requires `entity.act`, a controlled speaker, and
emits `SOUND` from the speaker's event-time position. `WHISPER`, `NORMAL`, `LOUD`, and `SHOUT`
change range and intensity deterministically.

Hearing a claim creates testimony evidence whose `immediate_source_entity_id` is the speaker and
whose `direct_witness` flag is false. Repeating the claim creates a new speech event and a new
evidence link to the new speaker. Clients cannot authenticate an arbitrary historical event by
submitting its ID as claimed provenance.

Ordinary movement is retained as a transient observation but is not automatically consolidated
into permanent memory. Dialogue, discoveries, injury, betrayal, and combat use progressively
higher memory salience.

## Player scene API

Players do not load canonical entity positions or raw event feeds. The Game Console selects an
embodied viewpoint and requests:

```text
GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{observer_entity_id}/scene
```

The response contains only perceived entities and observation presentations. Detail degrades from
`INSPECTED` to `IDENTIFIED`, `CLASSIFIED`, and `PRESENCE`; a distant presence may be rendered as an
anonymous figure without stats. The endpoint requires control of the viewpoint or privileged
`mind.read.all` / `world.read.all` authority. Administrators and DMs retain explicit canonical
inspection surfaces and can choose a controlled or privileged viewpoint for boundary testing.

## Acceptance behavior

The vertical slice proves that a normal statement in a tavern is heard by bodies in the room, not
by a body behind a closed door; opening the door or shouting changes the result deterministically;
entering afterward does not reveal the old event; repeating the statement produces testimony from
the repeater; one controller's remote bodies do not share knowledge; hidden entities do not appear
in the player scene; retries do not duplicate grants/evidence/memories; and a Player can move only
their assigned body.
