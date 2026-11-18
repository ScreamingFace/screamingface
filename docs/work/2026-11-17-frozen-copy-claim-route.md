---
ticket: OME-1947
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# frozen-copy-claim-route — the gateway claim route and its guard (unit B1)

## Intent

A sealed frozen copy that a leaderboard Score names must be kept. The scoreboard tells the gateway with a claim. Unit B1 adds the claim route `POST /v1/frozen-copies/{copy_id}/claim`, its guard (a list of permitted emails), and the store method that sets `claimed_at`.

Spec: `docs/spec/2026-11-16-frozen-copy-retention/`. Plan: `docs/plan/2026-11-17-frozen-copy-retention-stack-b.md` (owner approved 2026-11-17).

## Planned changes

Paths are under `apps/aigateway/`.
- `src/aigateway/config.py` (setting `frozen_copy_claim_emails`)
- `src/aigateway/core/auth/copy_claim.py` (new; guard `require_copy_claimer`)
- `src/aigateway/core/frozen_copy/store.py` (`ClaimOutcome`, `claim`)
- `src/aigateway/routes/frozen_copies.py` (route, `_not_sealed`)
- `charts/aigateway/values.yaml`, `templates/configmap.yaml`, `README.md`; `DEPLOYMENT.md`
- `tests/unit/test_frozen_copy_claim.py`, `tests/unit/test_chart_render_frozen_copy_claim.py` (new)
- No schema change (the column `claimed_at` is from migration 0018).

## Test plan

RED first. Test ids of `prd/score-claim.md`.
- K-5, K-6, K-7: the guard (each auth mode, empty list, peer, identity, email; the admin list and the claim list are separate).
- K-1, K-2: first claim sets `claimed_at`; a second claim gives `already` and the same time.
- K-3, K-4: `expired` and `abandoned` → 410; `open` → 409; unknown and malformed id → the same 404.
- Chart render: default empty, list with commas, one `allowFrom` element with two selectors.
- Invariant protected: only a `sealed` copy gets `claimed_at`, and only a caller of the claim list sets it.

## Acceptance

- `run_gates.py aigateway` all green; the Postgres lane green with `AIGW_TEST_PG=1`.
- No existing test is changed.
- An independent design review against the spec has no open major finding.

## Notes at start

- Owner order of 2026-11-17: both plans approved; build stacks B and C in parallel.
- The branch is cut from the stack A branch (commit a06fc9802), because pull request #1911 is not
  merged. After the merge of #1911, rebase the branch onto `origin/main`. The local gates use
  `--base` at the commit below this unit.
- The `tortoise-dev` companion skill is not installed on this machine. Code that touches the ORM
  follows the house pattern that the plan names.

## Outcome (fill at the end — required before COMMIT)

State on 2026-11-17: the code is built, reviewed and committed on the branch
`OME-1947-frozen-copy-claim-route`. `status` stays `in_progress` until the pull request is
merged.

- **Actual files:** as planned, plus:
  - `src/aigateway/core/frozen_copy/times.py` (new; `as_utc`) and
    `tests/unit/test_frozen_copy_times.py` (new). Review finding F2: the route needed the same
    "naive time from the database is UTC" rule as the sweep, so the rule moved out of
    `core/frozen_copy/sweep.py` (`_utc`) into one shared helper. `sweep.py` now imports it.
- **Commits:** one commit, `feat(aigateway): add the frozen copy claim route (OME-1947)`.
- **Gates:** `uv run .claude/scripts/run_gates.py aigateway --base a06fc9802` → ALL GATES GREEN.
  Postgres lane, `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`: 80 passed, 5 failed. The 5
  failures are all in `tests/integration/test_cache_snapshot_upload_postgres.py`: this machine
  has no `pg_dump`. This work does not touch that code. Stack B adds no Postgres test.
- **Design review:** verdict ACCEPT-WITH-FIXES, 10 low findings, none major. Fixed: F1 (chart
  README: a `from` element with only a `podSelector` selects pods of the gateway namespace), F2
  (one shared `as_utc`), F3 (no unreachable `None` branch for `claimed_at`), F5 (the guard calls
  the list check by a neutral name), F7 (docstring style), F8 (comment anchors), F9 (a test that
  the claim writes one INFO record with the copy id and no email). Open, low: F4 (the guard
  repeats the peer and identity sequence of `require_admin`; a shared helper would change
  `admin.py`), F6 (two small test helpers are copies of helpers in an existing test file; tests
  are append-only), F10 (a `delenv` call with no effect in the chart render test).
- **Deviations:**
  - `sweep.py` changes (see F2). The plan for C1 names `_utc`; C1 uses `as_utc` of `times.py`.
  - The comment in `charts/aigateway/templates/networkpolicy.yaml` has the same wrong words as
    the README had (F1). It is older than this work and not changed here.
  - No existing test is changed. No schema change.
