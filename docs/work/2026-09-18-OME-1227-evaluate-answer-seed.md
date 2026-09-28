---
ticket: OME-1227
stack: py-screamingface
status: in_progress
started: 2026-09-18
finished:
---

# OME-1227 — Accept a seed on sf.evaluate so a notebook can ask for a reproducible run

## Intent

Answer seeds (OME-1038) work end to end on `Client.evaluate`, which validates the seed at the
door (`_answer_seed_value`, OME-1193) and forwards it to both the Recipes path and the
complete-URL4 path. The module-level `sf.evaluate` — the call every `examples/*.ipynb` uses —
omits the keyword entirely, so the audience most likely to want a repeatable run is the one
that cannot ask for one: `sf.evaluate(..., answer_seed=42)` raises
`TypeError: evaluate() got an unexpected keyword argument 'answer_seed'`. This unit mirrors the
Client's signature in the wrapper.

Found while verifying imported-board runs on OME-1202 (three paid runs, all reporting
`answer_seed: null`).

## Planned changes

- `packages/screamingface/src/screamingface/_default_client.py` — add `answer_seed: int | None = None`
  to both `evaluate` overloads and the implementation, and forward it on BOTH branches (the
  complete-URL4 branch and the Recipes branch), mirroring `client.py`.
- `packages/screamingface/tests/` — a contract test that the keyword reaches the Client on both
  branches, written RED first.
- `packages/screamingface/tests/public_surface_snapshot.json` — regenerated; needs the owner's
  `--skip-append-only` approval.
- Ledger + `docs/tasks/` mirror.

## Test plan

Written RED first, against the production path (no shims):

- `sf.evaluate(recipe, benchmark=..., answer_seed=42)` forwards `answer_seed=42` to
  `Client.evaluate` — the invariant: the wrapper is a pass-through, not a narrower door.
- `sf.evaluate("<url4>", answer_seed=42)` forwards it on the complete-URL4 branch too — the
  branch most likely to be forgotten, since it takes neither `benchmark` nor `limit`.
- Omitting the keyword still forwards `answer_seed=None`, so an unseeded run's egress is
  unchanged and every request-keyed replay fixture stays valid. This is the regression the
  `apply_answer_seed` no-op invariant depends on.
- Existing `TypeError` guards for `benchmark`/`limit` on the URL4 branch keep firing.

## Acceptance

- `sf.evaluate(fusion, benchmark="inspect-gsm8k", limit=2, answer_seed=42)` returns a Report
  whose `answer_seed` is 42 rather than raising.
- Unseeded calls are unchanged.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `src/screamingface/_default_client.py` (both overloads, the
  implementation, and BOTH forwarding call sites), `tests/test_default_client_evaluate_passthrough.py`
  (new, RED first), `tests/public_surface_snapshot.json` (regenerated), plus `CHANGELOG.md`, which
  the snapshot test requires alongside a surface change.
- **Commits:** one on this branch, `Refs: OME-1227`.
- **Gates:** ruff check + ruff format + pyright (0 errors) + full pytest (1590 passed, 25 skipped)
  all green. `run_gates.py screamingface` STOPS at the append-only check — see Deviations.
- **Deviations:**
  - **The changelog already claimed this worked.** The Unreleased "Features" section carries
    `evaluate(answer_seed=…) sends X-Answer-Seed`, written from `Client.evaluate`'s perspective.
    That entry is what made the gap invisible: the feature genuinely shipped, just not on the door
    the notebooks use. Added a Bug Fixes entry rather than a second feature line, since the fix
    makes the existing claim true.
  - **Two `# type: ignore[call-overload]` in the new test.** The URL4 overload already types
    `benchmark`/`limit` as `None`, so a typed caller cannot reach the runtime `TypeError` guards.
    The guards still need testing because notebooks are untyped and that is the call they make.
  - **Append-only gate is the open item.** The regenerated `public_surface_snapshot.json` counts as
    a modified prior test artifact, so `run_gates.py` refuses. The diff is ONE line and purely
    additive (a new optional keyword on an existing signature; nothing removed or renamed).
    Needs the owner's `--skip-append-only` run — planned into the ticket from the start, not
    discovered late.
- **Owner-verify:** in a notebook kernel,
  `sf.evaluate(fusion, benchmark="inspect-gsm8k", limit=2, answer_seed=42)` returns a Report whose
  `answer_seed` is 42. Note `seed` is not portable across providers — a fusion containing an
  Anthropic member is only partially reproducible, so the honest check is two seeded runs diffed
  per case rather than an assumption.
