# Code review and user function test — 2026-08-20

Scope: full repository at `13f8747` (`claude/code-review-user-testing-ls3pd3`, identical to `main`),
with emphasis on the identity, authorization, and workspace code added by
`169abf3 Add account, player, and dungeon master workspaces`.

Both halves of the request were completed:

- **Code review** — read `identity/`, `kernel/api/app.py`, `domains/tabletop/portal.py`,
  `kernel/application.py`, `kernel/visibility.py`, and the `frontend/src/` feature adapters against
  the invariants in [`AGENTS.md`](../../AGENTS.md).
- **User function test** — ran the app in reference mode, signed in as the bootstrap administrator,
  created one DM account and one Player account, granted world roles, and exercised every workspace
  through both the HTTP API and a real Chromium browser.

Every claim below was reproduced against a running instance. Reproduction commands are included.

## Status

Findings §3.1 through §3.7 — every security finding — were **fixed in this branch** after the review
was accepted. Each carries a **Fixed** note describing the change, and each is covered by a
regression test in
[`tests/unit/kernel/test_api_authorization.py`](../../tests/unit/kernel/test_api_authorization.py)
or [`tests/unit/identity/test_identity_service.py`](../../tests/unit/identity/test_identity_service.py)
that was confirmed to fail against the pre-fix code. §3.8 through §3.10 are UI and documentation
items and remain open.

The findings are kept in their original form because the reproductions are the evidence; the
**Fixed** notes record what changed rather than rewriting history.

---

## 1. Verification lanes

| Lane | Command | Result |
| --- | --- | --- |
| Unit + contract tests | `uv run pytest -m 'unit or contracts' -q` | **127 passed** |
| Python lint | `uv run ruff check .` | **passed** |
| Type check | `uv run mypy kernel persona cognition population experiments domains identity infra main.py` | **passed** (89 files) |
| Frontend tests | `npm --prefix frontend run test` | **17 passed** (6 files) |
| Frontend lint | `npm --prefix frontend run lint` | **passed** |
| Frontend build | `npm --prefix frontend run build` | **passed**, `static/v2` byte-identical to the committed bundle |
| Browser journeys | Playwright against `tabletop-dm serve` | **passed** — see §2 |

Lanes **not** run, and why:

- **Integration / RLS / migration lane** (`TTDM_INTEGRATION=1 uv run pytest -m integration`) — not
  run at review time; every finding below was validated in reference mode. The affected code paths
  in `kernel/api/app.py` are shared by both modes, so findings §3.1–§3.6 apply to the durable stack
  as well; §3.5 is *worse* there because the client-supplied `actor_id` is what gets bound to
  `app.actor_id` for row-level security. **This lane has since been run** — see §5.
- **Packaged wheel verification** (`scripts/verify_wheel.py`) — no packaging change under review.

---

## 2. User function test

Run as `TTDM_OPERATOR_TOKEN=… uv run tabletop-dm serve`. Setting the operator token disables the
reference-mode loopback auto-admin ([`kernel/api/app.py`](../../kernel/api/app.py#L723)) so the real cookie login flow is
exercised end to end.

### 2.1 Administrator

| Step | Result |
| --- | --- |
| `GET /api/v2/auth/session` with no cookie | `401` ✅ |
| Login with a wrong password | `401`, message does not disclose whether the user exists ✅ |
| Login `admin` / `admin123` | `200`, `password_change_required: true` ✅ |
| Any API call before the password change | `403 password_change_required` ✅ |
| New password `short` | rejected (min length 12) ✅ |
| New password `administrator` | rejected as a common default ✅ |
| Valid password change | `200`, new session issued, flag cleared ✅ |
| Create account with username `a b` | rejected with the documented username rule ✅ |
| Create DM + Player accounts | `201`, each forced into a password change ✅ |
| Grant world role `SUPERUSER` | `400` — literal type rejects it ✅ |
| Grant `DM` / `PLAYER` per world | `200` ✅ |
| Remove own last `ADMIN` role | `400 the final administrator role cannot be removed` ✅ |
| Delete own account | `400` ✅ |
| Disable own account | `400` ✅ |
| Reset another user's password | `204`; that user's live session immediately `401` ✅ |
| Disable another account | live session immediately `401` ✅ |
| 5 failed logins | account locked; correct password then returns `account is temporarily locked` ✅ |

### 2.2 Dungeon Master (`dungeonmaster`, `DM` in Eclipse Keep)

| Step | Result |
| --- | --- |
| Forced password change on first login | ✅ |
| Session reports `has_dm_role: true`, `is_admin: false` | ✅ |
| `GET /api/v2/player/characters` | `403 a Player role is required` ✅ |
| `GET /api/v2/dm/worlds/{world}/eligible-users` | lists only role-holders in that world ✅ |
| Create game, set `max_players`, safety notes, house rules | `201` ✅ |
| Invite the player to the roster | `200`, member `JOINED` ✅ |
| Create a session with `dm_notes` | `201` ✅ |
| Session `SCHEDULED → LIVE → COMPLETED` | `started_at` / `ended_at` stamped correctly ✅ |
| Browser nav | shows only Game / Dungeon Master / Settings ✅ |
| Browser `/v2/admin`, `/v2/control`, `/v2/personas`, … | all redirect to Settings ✅ |

### 2.3 Player (`playerone`, `PLAYER` in Eclipse Keep)

| Step | Result |
| --- | --- |
| Forced password change on first login | ✅ |
| Build a character from fields | `201` ✅ |
| Generate a character from a seed | `201`, deterministic ✅ |
| Read another player's character | `403 only the character owner can edit this character` ✅ |
| Delete another player's character | `403` ✅ |
| `GET /api/v2/games` | shows only games they belong to ✅ |
| `GET /api/v2/games/{game}/sessions` | `dm_notes` redacted to `null` ✅ |
| `PATCH .../sessions/{id}` | `403 DM access to this game is required` ✅ |
| `POST /api/v2/dm/games` | `403 one of these world roles is required: DM` ✅ |
| All nine administrator-only API paths tested | `403` ✅ |
| Browser: submit console dialogue | event appears in the feed ✅ |
| Browser: rename display name in Settings | persisted, sidebar updates ✅ |

### 2.4 Browser sweep

All eleven workspaces were opened as each of the three accounts. Every page rendered its expected
headings with no uncaught page errors and no console errors other than the expected `401` from the
pre-login session probe. Role-aware navigation and the `RoleRoute` redirects behaved exactly as
`docs/API_AND_WORKFLOWS.md` describes.

**The product layer — accounts, characters, games, rosters, sessions, DM-note redaction — is
correct and well built.** Everything below concerns the kernel/control-plane API surface underneath
it.

---

## 3. Findings

### 3.1 🔴 Critical — `POST /api/v2/commands` takes `actor_id` from the request body

[`kernel/api/app.py`](../../kernel/api/app.py#L1320-L1328)

```python
payload.setdefault("actor_id", str(demo["actor_id"]))
proposal = CommandProposal.model_validate(payload)
receipt = simulation.submit(proposal)
```

The command's actor is whatever the caller sends, defaulting to the demo GM actor. The session user
is never consulted. `simulation.submit` faithfully checks world capability and entity control — but
for the *attacker-chosen* actor.

Reproduced with an account holding **no global role and no world role at all**:

```console
$ curl -b nobody.jar -X POST $B/api/v2/commands -H 'Content-Type: application/json' -d '{
    "command_type":"tabletop.spatial.move","world_id":"…","branch_id":"…","run_id":"…",
    "embodied_entity_id":"<GM-controlled hero>","parameters":{"dx":1,"dy":0},
    "idempotency_key":"nobody-mv-2"}'
```

Hero position before: `(2, 3)` → after: `(3, 3)`. Canonical state was mutated, and the append-only
event ledger recorded `actor_id` as the administrator's actor, not the account that made the
request. Passing `actor_id` explicitly lets any authenticated account impersonate any actor in any
world, including `canonical.promote`.

This breaks four [`AGENTS.md`](../../AGENTS.md) invariants at once: world-scoped capability, no union of authority
across worlds, canonical writes require commit authority, and the reproducibility of the decision
record.

Note that this is also what makes the Game Console appear to work for players: the frontend
([`frontend/src/features/game-console/api.ts`](../../frontend/src/features/game-console/api.ts#L57-L70)) sends no `actor_id`, so **every** user's console
command silently executes as the demo GM.

**Fixed.** `submit_command` now resolves the actor through a new `requested_actor_id` helper: a
browser session always acts as the actor its account owns, and naming any other actor is rejected
with `permission_denied`. Only the operator/automation boundary may still name one, because it has
no account of its own. The route also calls `require_world_access` before submitting. The
documented contract in [`docs/API_AND_WORKFLOWS.md`](../API_AND_WORKFLOWS.md) was updated to match,
and `test_session_cannot_submit_a_command_as_another_actor`,
`test_command_is_attributed_to_the_signed_in_actor`, and `test_roleless_account_cannot_mutate_a_world`
cover it.

The Game Console keeps working for players because world-role grants now provision real kernel
authority (see §3.3's fix): a Player receives `world.read`, `action.propose`, and `action.commit`,
so their dialogue commits under **their own** actor. They receive no `entity.control`, so
`test_player_cannot_act_through_an_entity_it_does_not_control` confirms they can no longer move a
character the DM controls.

### 3.2 🔴 Critical — `POST /api/v2/actors` mints arbitrary capabilities with no role check

[`kernel/api/app.py`](../../kernel/api/app.py#L1179-L1190)

The route has no `require_admin`, and `/api/v2/actors` is absent from the `admin_workspaces` prefix
list at `:775`. Any authenticated account can create an actor with any capability set in any world:

```console
$ curl -b player.jar -X POST $B/api/v2/actors -H 'Content-Type: application/json' -d '{
    "display_name":"Escalated","kind":"HUMAN","roles":["ADMIN"],
    "capabilities":["action.commit","entity.control","entity.read.secret",
                    "canonical.promote","mind.write.all","world.read.all"],
    "world_id":"<any world>"}'
201 Created
```

`simulation.create_actor` calls `grant_authority` ([`kernel/application.py`](../../kernel/application.py#L171-L193)), which writes
straight into `world_authorities` and — in durable mode — is synced to the control plane by the next
`durable_control.sync(simulation)`. Chained with §3.1 this is a complete, persistent privilege
escalation from any account to full canonical authority.

**Fixed.** Both the `GET` and `POST` branches now call `IdentityService.require_admin`. Listing is
gated too: the response carries every actor's capability set, which is reconnaissance for exactly
this escalation. `test_only_administrators_may_mint_actors` covers it.

### 3.3 🟠 High — no world-scoped read authorization on any control-plane read route

`worlds()` (`:1140`), `world_detail()` (`:1166`), `world_actors()` (`:1196`), `entities()` GET
(`:1206`), `runs()` GET (`:1281`), `world_runs()` (`:1288`), `branches()` (`:1294`),
`all_snapshots()` (`:1305`), and `replay()` (`:1701`) authenticate but never check world role.

Reproduced: the administrator created a second world, "Secret Vault", granting no roles to anyone.
A Player-role account in a *different* world — and a roleless account — could both read it:

```console
$ curl -b player.jar $B/api/v2/worlds
['Eclipse Keep', 'Secret Vault']

$ curl -b nobody.jar $B/api/v2/worlds/$W2/actors
[{"actor_id":"…","capabilities":["world.read.all","entity.read.secret","canonical.promote", …]}]

$ curl -b nobody.jar $B/api/v2/branches/$CANONICAL/replay
{"projections":{"tabletop.entities":{ …full canonical projection… }}}
```

The world switcher in the browser confirms it: signed in as `playerone`, the "Active world"
dropdown offers **Secret Vault**. [`AGENTS.md`](../../AGENTS.md) requires world-scoped capability and forbids unioning
authority across worlds; these routes do neither.

Positively: `secret_state` is correctly excluded from both the entity list payload (`:1219`) and the
projections, so the hidden-evidence boundary itself holds. What leaks is world membership, entity
rosters, positions, HP, inventories, gold, actor capability sets, and branch lineage.

**Fixed.** Two helpers were added. `require_world_access` authorizes a single world — administrator,
or a `DM`/`PLAYER` grant **for that world** — and now guards `world_detail`, `world_actors`,
`entities`, `world_runs`, `snapshots`, `replay`, and command submission. `world_readable` filters the
collection routes so a world the caller cannot read is invisible rather than merely unreadable.

The underlying gap was that a product role never reached the kernel at all in reference mode, and
only after a restart in durable mode. `identity.repository.kernel_authority` is now the single
source of truth translating product roles into actor roles and capabilities, and it feeds both the
durable `sim.actor_capabilities` rows and the in-process authority table, which is re-provisioned on
sign-in, on any role change, and on world creation. `test_world_reads_are_scoped_to_granted_worlds`,
`test_branch_replay_is_world_scoped`, and `test_world_role_grant_provisions_kernel_authority` cover
it.

### 3.4 🟠 High — `GET /api/v2/events` accepts an arbitrary `actor_id`, bypassing visibility

[`kernel/api/app.py`](../../kernel/api/app.py#L1338-L1339)

```python
actor_id = uuid.UUID(request.args.get("actor_id", str(demo["actor_id"])))
… simulation.visible_events(actor_id)
```

`VisibilityPolicy.event_for` ([`kernel/visibility.py`](../../kernel/visibility.py#L11-L15)) releases an event when the actor is in
`visible_to` **or** holds `world.read.all`. Since the caller picks the actor, any account can read
the event stream of the GM actor, which holds `world.read.all`. The same pattern appears at
`:1646` for `GET /api/v2/entities/{id}/mind`, where in durable mode the client-supplied `actor_id`
is passed into `mind_repository.inspect(..., actor_id=actor_id)` and becomes the transaction-local
`app.actor_id` — i.e. it selects which RLS identity the query runs under.

**Fixed.** Both routes resolve the actor through `requested_actor_id`, so the query parameter is
honoured only for the operator/automation boundary. `GET /api/v2/events` additionally filters to the
caller's readable worlds. `test_event_reads_cannot_borrow_another_actors_visibility` covers it.

### 3.5 🟠 High — client-chosen actor on the cognition write routes

- `cognition_decide` (`:1359`): `actor_id = body.actor_id or demo["actor_id"]`
- `cognition_observe` (`:1508`): `simulation.authority(event.world_id, body.observer_actor_id)`

Both then check "does *that* actor control this entity", which is vacuous when the caller names the
actor. `cognition_runtime` (`:1478`) and `cognition_relationship` (`:1586`) get this right with
`current_actor_id()` — the inconsistency is the bug.

**Fixed.** `cognition_decide` and `cognition_observe` now resolve their actor through
`requested_actor_id` and check `require_world_access` first, matching their sibling routes.
`ObservationRequest.observer_actor_id` became optional, since a session no longer needs to send it.

### 3.6 🟡 Medium — `/api/v2/trials` missing from the administrator prefix list

[`kernel/api/app.py`](../../kernel/api/app.py#L775-L784) lists eight administrator prefixes but not `/api/v2/trials`, even though
`/api/v2/experiments` — which has no routes at all — is listed. Trial outputs are administrator
experiment data:

```console
$ curl -b nobody.jar $B/api/v2/trials/$TRIAL_ID
{"canonical_hash_after":"86d4c5b…","events":[{"actor_id":"…","branch_id":"…", …}], …}
```

**Fixed.** The dead `/api/v2/experiments` entry was replaced with `/api/v2/trials`.
`test_trial_results_require_the_administrator_role` covers it. The prefix list remains fragile by
construction — a per-route decorator would prevent the next route from being missed — and that
refactor is left open.

### 3.7 🟡 Medium — the final-administrator safeguard counts disabled administrators

[`identity/service.py`](../../identity/service.py#L263-L264)

```python
def _admin_count(self) -> int:
    return sum(account.is_admin for account in self.repository.list_accounts())
```

`is_active` is ignored, so a disabled administrator still satisfies the `> 1` guard at `:184` and
`:216`. An installation can be permanently locked out of administration:

```console
$ uv run python -                       # reproduction
admins: ['admin', 'admin2']
after disabling admin2 -> active admins: ['admin']
after admin drops own role -> ACTIVE ADMINS: []
RESULT: LOCKED OUT - no usable administrator
```

[`AGENTS.md`](../../AGENTS.md) says "Do not remove the final-administrator safeguards"; this is a hole in them rather
than a removal, but the outcome is the same. The same counting bug lets `delete_user` remove the
last usable administrator.

**Fixed.** `_admin_count` now counts only administrators who can still sign in, and takes an
`excluding` argument so each guard asks the precise question "would any usable administrator remain
after this?". Disabling the last active administrator is refused as well, which was previously
possible from a second administrator account.
`test_disabled_administrators_do_not_satisfy_the_final_administrator_guard` and
`test_the_last_active_administrator_cannot_be_disabled` cover it.

### 3.8 🟡 Medium — the Game Console event feed shows raw command types

[`frontend/src/features/game-console/api.ts`](../../frontend/src/features/game-console/api.ts#L12) builds its own summary:

```ts
summary: String(raw.summary ?? payload.summary ?? payload.message ?? raw.event_type ?? "Event recorded"),
```

The kernel emits no `summary` for most events, so the player-facing feed renders
`tabletop.entity.spawn / tabletop.entity.spawn` and `tabletop.spatial.move / tabletop.spatial.move`
— the machine name twice — for everything except `tabletop.console.submit`. Confirmed in the
browser (see the Event feed panel).

[`frontend/src/features/run-inspector/eventPresentation.ts`](../../frontend/src/features/run-inspector/eventPresentation.ts) already exports `eventSummary()`, which
humanizes the type and folds in payload details. `normalizeEvent` neither calls it nor keeps
`payload`, so the console could not use it even if it wanted to.

**Fix:** carry `payload` through `normalizeEvent` and render with the shared `eventSummary()`. This
is exactly the reuse that [`AGENTS.md`](../../AGENTS.md) asks for with the typed feature adapters.

### 3.9 🟡 Medium — the administrator audit log has no UI

`GET /api/v2/admin/audit` is implemented (`:940`), documented in [`docs/API_AND_WORKFLOWS.md`](../API_AND_WORKFLOWS.md)
("Review append-only account activity in the admin audit view"), and listed in [`README.md`](../../README.md) as an
Admin Dashboard capability ("inspect audit history"). `rg -n 'audit' frontend/src/` finds only
the unrelated Run Inspector decision panel. The Admin Dashboard renders no audit view, and
[`frontend/src/features/admin/api.ts`](../../frontend/src/features/admin/api.ts) has no adapter for the route.

**Fix:** add the adapter and panel, or amend both documents. Per [`AGENTS.md`](../../AGENTS.md) the docs must move in
the same change as the behavior.

### 3.10 🔵 Low — cosmetic and consistency items

1. **Roleless accounts are labelled "Player."**
   [`frontend/src/features/admin/AdminDashboardPage.tsx`](../../frontend/src/features/admin/AdminDashboardPage.tsx#L155-L162) ends its ternary chain with a bare
   `"Player"` default, so an account with no roles reads `@nobody · Player` in the directory while
   the "Players" counter above correctly excludes it. Add a `"No roles"` branch.

2. **The login page hard-codes the bootstrap credentials forever.**
   The username field is pre-filled with `admin` and the hint "First start: use **admin** and
   **admin123**" is shown to every visitor permanently, long after the password has changed — and to
   players, who now learn the administrator's username. [`tests/e2e/test_application_journeys.py`](../../tests/e2e/test_application_journeys.py#L44-L45)
   asserts this. Suggest hiding it once the bootstrap password has been changed.

3. **`max_players` is never enforced.** `TabletopPortalService.set_member`
   ([`domains/tabletop/portal.py`](../../domains/tabletop/portal.py#L617-L647)) accepts members past the game's `max_players`; the UI
   shows `1/4 seats` but nothing rejects the fifth.

4. **`PATCH .../sessions/{session_id}` creates a session for an unknown id.**
   `save_session` (`portal.py:672-709`) falls through to `session_id or uuid.uuid4()` when no
   existing row matches, so a PATCH against a nonexistent session silently creates one. Raise
   `KeyError` instead.

5. **Character `world_id` is not role-checked.** `create_character` / `update_character`
   (`portal.py:499-562`) accept any `world_id` without verifying the owner holds `PLAYER` there.

6. **A locked account's lockout extends on every further attempt.**
   `IdentityService.login` (`identity/service.py:48-53`) increments `failed_login_count` and resets
   `locked_until` even while the account is already locked, so an attacker can hold a victim locked
   out indefinitely. Skip the failure record when `locked_until` is still in the future.

7. **`current_user()` is annotated `AuthenticatedUser` but returns `UserAccount` under the operator
   token.** `:722-727` and `:734-737` assign `identity.bootstrap_admin` (a `UserAccount`) to
   `g.current_user`; `current_user()` (`:673-677`) declares `AuthenticatedUser`. Nothing reads
   `session_id` today, so it is latent, and `mypy` cannot see it through `g`.

8. **No `ProxyFix`, so `secure=request.is_secure` under-secures the cookie behind a TLS proxy.**
   `session_cookie` (`:690-700`) derives the `Secure` flag from the WSGI scheme. The Compose stack
   binds to loopback and terminates no TLS, so this is not exploitable as shipped — but it is a trap
   for anyone fronting the app with nginx. Worth a line in `docs/OPERATIONS.md`.

---

## 4. What is good

Worth stating plainly, because the findings above are concentrated in one layer:

- **The identity module is solid.** `scrypt` with per-password salt and `hmac.compare_digest`, a
  dummy hash to equalize timing on unknown usernames, SHA-256 session-token hashes at rest, forced
  first-login password change, lockout, session revocation on password reset and on account
  disable — all verified working, not just present.
- **The product authorization layer is correct.** Character ownership, game membership, DM-note
  redaction, and the `DM`/`PLAYER` world-role split all enforce server-side and were confirmed by
  negative tests, not just happy paths.
- **`secret_state` never leaks.** Every projection and entity payload I could reach as a
  low-privilege user excluded it.
- **The frontend does not mask authorization failures.** `endpointUnavailable`
  ([`frontend/src/core/api/client.ts`](../../frontend/src/core/api/client.ts#L52-L54)) deliberately excludes `401`/`403` from the demo-fallback list, which
  is precisely what [`AGENTS.md`](../../AGENTS.md) requires.
- **The build is reproducible.** `npm run build` reproduced the committed `static/v2` bundle
  byte-for-byte — `git status` stayed clean.
- **Lint, types, and tests are green** across every lane that can run without Docker.

---

## 5. Remaining work

Findings §3.1–§3.7 are fixed on this branch. What is still open:

1. **§3.8** — carry `payload` through `normalizeEvent` and render the Game Console feed with the
   shared `eventSummary()`.
2. **§3.9** — add the Admin Dashboard audit view, or amend
   [`README.md`](../../README.md) and [`docs/API_AND_WORKFLOWS.md`](../API_AND_WORKFLOWS.md) to stop
   promising it.
3. **§3.10** — the eight low-severity items, of which the lockout-extension issue (item 6) is the
   only one with a security flavour.
4. **Integration coverage — now closed.** The durable lane was subsequently run against
   PostgreSQL 16 and Redis 7, and
   [`tests/integration/test_durable_authorization.py`](../../tests/integration/test_durable_authorization.py)
   was added to prove local and RLS authorization reach matching outcomes, per
   [`AGENTS.md`](../../AGENTS.md). All 33 integration tests pass.

Item 6 of §3.10 (lockout extension) was also fixed, since it carried security weight and the patch
was contained to `IdentityService.login` and one repository method.
