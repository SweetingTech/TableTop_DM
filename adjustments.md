# Adjustments

A running log of changes made during the recent onboarding-experience work,
each paired with the problem it solves. Newest entries on top.

## 1. Playwright e2e suite for the landing-page guided tour

**Problem:** The new in-app tour (see entry 4) was hand-tested in the browser
but had no automated coverage. Any future template/JS change could silently
break the welcome flow that brand-new users hit.

**Fix:**
- Added 6 Playwright tests in `tests/e2e/test_landing_tour.py` covering
  auto-start on first visit, the spotlight on the **+ New Campaign** button,
  the wizard handoff, the Local AI step, the skip flow, and the
  *Take the guided tour* relaunch link.
- Pinned `playwright==1.59.0` and `pytest-playwright==0.7.2` in
  `requirements-dev.txt`.
- Registered an `e2e` pytest marker in `pyproject.toml` so the suite is
  opt-in (`pytest -m e2e`); existing `make unit / contracts / integration`
  targets are untouched.
- Added a `tests/e2e/conftest.py` that defaults pytest-playwright to
  capture **video, screenshot, and trace on failure only** into
  `test-results-e2e/` (gitignored).
- Added `make e2e` and `make e2e-install` convenience targets.
- Added `.github/workflows/e2e.yml`: spins up postgres/redis/qdrant via the
  existing compose file, runs migrate + seed, boots `python app.py`, waits
  for `/health`, runs the Playwright suite, and uploads artifacts on
  failure. Triggers only on changes to templates/static/app/tests/workflows
  to keep PR runtime down.

Verified locally: 6/6 pass in ~11s.

## 2. Local LM Studio auto-detection latency fixed (4s → ~25ms)

**Problem:** The wizard's "Local AI" probe was slow and unreliable on Windows:
- Cold start: ~4100ms (first call after Flask reload), often hitting the
  client-side 4s timeout and making LM Studio appear absent even when running.
- Warm: ~1500ms — caused by Windows' `localhost` resolving to `::1` first,
  then waiting for the IPv6 SYN to fail before falling back to IPv4 (LM
  Studio listens on `0.0.0.0`/IPv4 only).

**Fix:** Added `GET /api/ai/detect_local` in `app.py` which:
- Uses a lightweight inline `_LOCAL_PROVIDER_DEFAULTS` dict instead of
  importing `services.llm.adapter` (which transitively pulls
  pydantic/schemas), eliminating the cold-start hit.
- Probes `127.0.0.1` directly with `urllib.request`, sidestepping the IPv6
  dual-stack stall.

Result: cold ~2ms, warm ~16–27ms, sad-path ~1.5s.

## 3. Wizard auto-detects whatever LM Studio currently has loaded

**Problem:** Manual AI configuration was friction for first-run users — they
had to know what LM Studio is, where it serves, and what model name to type.

**Fix:** Added a "Local AI" block to wizard step 1 that fires
`GET /api/ai/detect_local?provider=lmstudio` on open. Three states (probing,
detected, unavailable) with clear UI for each. When detected, a checkbox
("Use this model for DM & NPC narration") opt-in writes the LM Studio
config to the new campaign via `PUT /api/campaigns/<id>/ai_config`. When
absent, the wizard falls back gracefully and tells the user AI features
will use the mock provider.

## 4. Guided tour for first-time visitors

**Problem:** Even with a "Get Started" hero and a wizard, first-time users
didn't know *where to look* or what each piece meant. The user wanted
"the user to START on the page you go to by default, and then little tool
tip pop ups helping them set up their first game."

**Fix:** Added a self-contained 11-step Tour module to `templates/index.html`:
- Spotlight overlay (fixed-position element with a giant `box-shadow`
  cutout) plus a tooltip card whose placement is auto-chosen from
  `bottom/top/left/right` to never overflow the viewport.
- Auto-starts ~400ms after first page load when no
  `localStorage.ttdm_tour_done_v1` flag is set; persists completion.
- "Skip tour" available on every step; "Take the guided tour" link in
  both welcome-hero variants re-launches it on demand.
- The `Wizard` object now dispatches `wizard:opened`, `wizard:step` (with
  `detail.step`), and `wizard:closed` `CustomEvent`s. The Tour listens
  for these and advances automatically when the user takes the expected
  action — the tour never drives the wizard, it follows it.

## 5. New-campaign wizard + Get Started landing section

**Problem:** New users landing on `/` with no campaigns saw a sparse
dashboard with no obvious entry point — and even with one campaign, getting
into a playable session required several manual steps.

**Fix:** Added (all in `templates/index.html`, no backend changes — all four
endpoints already existed):
- A "Get Started" section at the top of `/` with two states:
  - empty → centered welcome card + single **+ New Campaign** CTA.
  - non-empty → compact CTA row + clickable *Resume* tiles for each
    campaign. The seeded "Eclipse Keep" gets a small `Demo` badge.
- A 4-step modal wizard that creates campaign → optional character →
  optional session → summary, calling existing endpoints
  (`POST /api/campaigns`, `POST /api/campaigns/<id>/entities`,
  `POST /api/campaigns/<id>/sessions`).
- Resume tiles call `POST /api/campaigns/<id>/resume` and jump to `/game`
  so users land in a playable state in one click.

## 6. Database race / environment cleanup (earlier in session)

**Problem:** App startup intermittently failed with database race conditions
and an environment whose Python site-packages drifted from the docker stack's
expectations.

**Fix:** Re-ran `infra/scripts/migrate.sh` + `infra/scripts/seed_demo.sh`
against a fresh compose stack and re-installed pinned dependencies from
`requirements-dev.txt` + `pyproject.toml`'s `[project] dependencies`. App
came up cleanly on `:8000` and `/readyz` returned green.

## Files touched (this onboarding work)

| File | What changed |
|---|---|
| `templates/index.html` | Get Started hero, wizard modal, Local AI block, Tour module, CSS |
| `app.py` | Added `/api/ai/detect_local` route + `_LOCAL_PROVIDER_DEFAULTS` |
| `tests/e2e/test_landing_tour.py` | NEW — 6 Playwright tests for the tour |
| `tests/e2e/conftest.py` | NEW — defaults trace/video/screenshot capture on failure |
| `tests/e2e/__init__.py` | NEW — package marker |
| `requirements-dev.txt` | Pinned `playwright` + `pytest-playwright` |
| `pyproject.toml` | Registered `e2e` marker |
| `Makefile` | Added `e2e` and `e2e-install` targets |
| `.gitignore` | Ignore `test-results-e2e/`, `.playwright/` |
| `.github/workflows/e2e.yml` | NEW — CI job that boots app + runs Playwright |
| `adjustments.md` | NEW — this file |

## How to run things

```bash
# Local dev: regular tests (no e2e)
make ci-fast          # lint + format + typecheck + unit + contracts

# Local dev: e2e (one-time setup)
make e2e-install      # downloads chromium browser binary (~180 MB)

# Local dev: run e2e (requires app running on :8000)
make e2e
# or:  pytest -m e2e tests/e2e -v

# CI: triggered automatically on PRs that touch templates/static/app/tests
```
