# SECURITY_VISIBILITY
Status: Phase 2.3 enforcement specification.

## Visibility assignment (`visible_to`)
Visibility is resolved at commit-time by orchestrator policy, not by clients.

Inputs:
- event type
- sender role
- target entities/principals
- current encounter/session participants
- intervention contract defaults (if applicable)

Resolution order:
1. Start from event default scope template.
2. Apply policy expansions (e.g., GM always included).
3. Apply policy reductions (e.g., secret whisper excludes unrelated players).
4. Deduplicate and persist as sorted UUID array in `visible_to`.

## Canonical scopes
- **DM-only**: only GM/DM principals + system auditing principal.
- **gods-only**: god principals participating in current campaign + GM.
- **party-only**: active player principals in the same party + GM.
- **telepathy pair**: exactly sender principal + target principal + GM.

Notes:
- GM inclusion is mandatory for moderation, arbitration, and replay audit.
- System principal inclusion is optional and reserved for backend observability channels.

## Enforcement strategy
Primary strategy: Postgres RLS.

### RLS contract
- Each request/connection sets `SET app.principal_id = '<principal_uuid>'`.
- Tables with visibility arrays enforce policy:
  - `USING (current_setting('app.principal_id', true)::uuid = ANY(visible_to))`
  - `WITH CHECK` variant for service-managed inserts (only trusted service role writes)

### Data-layer mandatory filters (fallback)
If a service cannot use RLS (e.g., analytics replica), every query must include:
- `WHERE $principal_id = ANY(visible_to)`

This fallback is allowed only for read paths and must be covered by integration tests.

## Principal authentication
- External identity provider issues JWT/OIDC token.
- API gateway validates token and extracts `sub`.
- Orchestrator maps `sub` -> `principals.auth_subject`.
- The mapped `principal_id` is injected into DB session context and into audit logs.

Service-to-service:
- mTLS or signed service token with scoped claims.
- Services impersonating users must include `on_behalf_of_principal_id` and are auditable.

## Test plan
1. **Positive read tests**: principal can read events where included in `visible_to`.
2. **Negative read tests**: principal cannot read DM-only events without membership.
3. **Scope correctness tests**: telepathy events visible only to pair + GM.
4. **RLS bypass tests**: direct table query with unset/invalid `app.principal_id` returns zero rows.
5. **Parity tests**: RLS output equals fallback-query output for same principal and session.
6. **Audit tests**: every committed event has non-empty `visible_to` and includes GM where required by policy.
