# TableTop DM Architecture and Completion Review

Date: 2026-05-19
Original review: Gemini CLI
Closure-pass author: Codex
Status: Current-state validated against README and CHANGELOG

---

## 1. Purpose

This document is the canonical architecture and completion review for the current release-candidate track.

It replaces prior mixed snapshots that combined:
- historical findings from pre-closure QA,
- intermediate recommendations, and
- post-fix closure notes.

The goal is to state one truthful current assessment of what is complete, what is aligned, and what remains.

---

## 2. Sources and Method

Primary sources:
- README implementation status and prime directives
- CHANGELOG phase history and closure claims
- Current code structure and tests in this repository

Method:
1. Validate document claims against current code surfaces.
2. Confirm closure items that were previously marked as blockers.
3. Separate completed work from remaining release hardening.

---

## 3. Executive Assessment

Overall grade: Strong Architecture, RC Track Healthy (not final GA sign-off)

Summary:
- The architecture is technically sound and consistent with deterministic engine constraints.
- Phase 44 and Phase 45 closure items are implemented and reflected in code/tests.
- The former route-layer security gaps are treated as closed in current code and route matrix coverage.
- Remaining work is primarily RC hardening and productization, not foundational redesign.

Release implication:
- The project is in a credible pre-1.0 RC posture.
- Remaining risks are in breadth/depth of hardening, not core architecture correctness.

---

## 4. Architecture Integrity (Current Truth)

### 4.1 Deterministic contract remains intact

The core path remains:
Proposal -> Validation -> Auth/Resource Check -> Tool Call -> State Delta -> Ledger Event -> Broadcast

This aligns with the README prime directives and current orchestrator implementation.

### 4.2 API composition has been refactored as claimed

Current state:
- app.py is a small launcher/composition root.
- Flask routes and Socket.IO wiring live in services/api/application.py.
- Shared API helpers exist in services/api/auth.py and services/api/responses.py.
- API routes are registered through a Flask blueprint.

This is aligned with Phase 45 closure statements. The route surface is centralized behind a blueprint and shared helpers have been extracted, but the per-domain physical split of `services/api/application.py` into separate route-family modules is intentionally deferred to post-1.0 maintainability work. The public URLs and response contracts remain stable for the RC.

### 4.3 State delta application is no longer hardcoded in pipeline branches

Current state:
- OrchestratorPipeline delegates committed deltas to StateDeltaDispatcher.
- Dispatcher is registry-backed and explicit about supported table/operation pairs.
- Unknown operations raise a structured unsupported-delta error.

This closes the earlier maintainability concern around inline branching.

### 4.4 Campaign cascade behavior moved toward DB ownership

Current state:
- Migration 015 introduces broad FK on-delete behavior for campaign cleanup paths.
- Campaign lifecycle deletion is centralized and reused by import-replace flows.
- Ledger delete remains explicit where append-only ledger semantics require it.

This is technically sound and consistent with data-model intent.

---

## 5. Security and Visibility Assessment

### 5.1 Route-layer auth and visibility posture

Current state indicates closure of the prior class of route leaks:
- Session reads require principal context.
- Non-member access is rejected.
- Player widening to DM scope is blocked/silently narrowed where applicable.
- Story state GM/private data is redacted for non-GM reads.
- Story-state/mode/entity mutations require GM/system identity with local join-token enforcement where required.

### 5.2 Error disclosure boundary

Current state:
- JSON error responses suppress traceback details by default.
- Trace/detail are included only when TTDM_DEBUG is enabled.

This closes the previous traceback disclosure risk pattern.

### 5.3 Exception boundary governance

Current state:
- Broad route-layer catches must be marked as defensive boundaries.
- Contract test enforces explicit boundary annotation in route boundary files.

This is a strong guardrail against silent broad-catch regressions.

---

## 6. AI, RAG, and Session Intel

### 6.1 Provider and local-model behavior

Current state:
- Multi-provider adapter support is concrete.
- Local providers no longer silently inherit OpenAI embedding defaults.
- Local embedding model selection/setup behavior is provider-aware and fails clearly when missing.

### 6.2 Session Intel resilience

Current state:
- Extractor schema uses explicit enums for key fields.
- Safe event-type aliases are canonicalized.
- Invalid structured outputs receive a constrained correction retry.
- Skip reasons are retained for diagnostics.

### 6.3 RAG and visibility

Current state remains aligned with prior architecture:
- Purpose-based retrieval surface.
- Visibility-aware filtering for chunk access.
- RAG-backed extraction events force DM review when appropriate.

---

## 7. Frontend and Runtime Surface

Current state:
- Game Console and Control Plane now load module entrypoints:
  - static/js/game/main.js
  - static/js/control/main.js
- Compatibility stubs remain for legacy script paths.

This is an incremental modularization strategy that improves maintainability without breaking templates.

---

## 8. Testing and Verification Posture

The closure narrative is backed by concrete verification surfaces:
- Service tests (dispatcher and domain behavior)
- Contract tests (exception boundary guard)
- Integration tests (route auth matrix and visibility paths)
- Node syntax checks for new JS entrypoints
- Boot verification and E2E smoke

Assessment:
- Coverage is materially stronger than pre-closure state.
- The highest-risk previously reported route/auth regressions are now encoded in regression tests.

---

## 9. Completion Matrix (Review Items)

| Item | Current status | Notes |
|---|---|---|
| app.py decomposition and API blueprinting | Closed | Entrypoint is small; route stack moved under services/api |
| Shared auth/error/serialization helpers | Closed | Centralized under services/api helpers |
| Hardcoded delta application | Closed | Replaced with StateDeltaDispatcher delegation |
| Campaign cascade SQL duplication risk | Closed | Lifecycle service + migration 015 FK behavior |
| Route-layer auth and visibility gaps | Closed for addressed surface | Covered in route auth matrix tests |
| DIALOGUE omission from chat history | Closed | DIALOGUE included in filtered chat/resume flows |
| Traceback disclosure in JSON errors | Closed | Debug-gated trace/detail behavior |
| start.ps1 stderr-progress handling | Closed | Nonzero exit semantics used for failure detection |
| Frontend module entrypoint split | Closed | Module entrypoints with compatibility stubs |
| Session Intel weak-local-model resilience | Closed | Enum constraints, canonicalization, correction retry |
| Local embedding default mismatch | Closed | Provider-aware embedding model selection |

---

## 10. Remaining Work (RC Hardening)

The remaining backlog is release hardening, consistent with README and CHANGELOG RC direction:

1. Product-grade identity and join UX polish.
2. Additional reconnect/cursor-gap edge-case coverage.
3. Documentation reality pass across user-facing help content.
4. Packaging and performance smoke for release readiness.
5. Continued expansion of route/auth matrix breadth as surface area evolves.

None of the above requires a change to the core architecture model.

---

## 11. Final Verdict

This codebase now reflects the architecture it claims:
- deterministic backend authority,
- principal-scoped visibility controls,
- explicit route-layer auth boundaries,
- modular service decomposition,
- and RC-grade verification workflows.

The correct interpretation is:
- architecture and closure implementation are complete for the reviewed findings,
- release hardening remains active before final 1.0 ship.

That is a healthy and technically credible RC posture.
