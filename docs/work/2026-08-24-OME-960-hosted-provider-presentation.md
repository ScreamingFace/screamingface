---
ticket: OME-960
stack: screamingface
status: in_progress
started: 2026-08-24
finished:
---

# OME-960 — Render hosted provider statuses without BYOK controls

## Intent

Make hosted provider availability truthful for the signed-in caller while keeping credentials and
provider mutation controls local-only.

## Planned changes

- Add the OME-960 task, spec, plan, and ledger artifacts.
- Update `packages/screamingface/tests/test_connection_panel.py` test-first.
- Update the shared presentation logic and status styling in
  `packages/screamingface/src/screamingface/_ui/connection_view.py`.

## Test plan

- Connected hosted providers remain Connected and carry the ScreamingFace availability source.
- Hosted providers reported `not_connected` render Unavailable, never Connected.
- Hosted pending/error/reauth states collapse to the caller-relevant Unavailable presentation.
- Static HTML, widget text, and repr agree.
- Hosted mutation controls remain absent; local loopback BYOK controls remain unchanged.

## Acceptance

- The observable Client behavior matches the approved OME-960 spec.
- Focused tests and the full ScreamingFace quality gates pass.
- The work is committed locally without opening a PR.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** task/spec/plan/ledger artifacts; one shared connection-panel presentation
  projection; SFDS status styling; focused hosted presentation coverage in
  `test_connection_panel.py`.
- **Commits:** `feat(screamingface): show hosted provider availability`; review follow-up
  `fix(screamingface): hide hosted credential lifecycle states` (this commit).
- **Gates:** 39 focused connection-panel tests passed; complete `screamingface` gate runner passed
  Ruff, format, Pyright, 95% coverage pytest, notebook checks, build, and distribution checks after
  the review follow-up.
- **Deviations:** the append-only test check was skipped after it correctly identified the
  intentional, owner-approved replacement of OME-883's obsolete all-hosted-connected assertion.
  It was skipped again for the reviewer-requested replacement of the weak pending/error substring
  assertion with an exact cell contract. No test guard or gate configuration was changed.

## Review follow-up

### Planned changes

- Strengthen hosted status tests to assert the exact status cell, class, label, source, and repr.
- Replace the split `_provider_status`/`_provider_presentation` decisions with one projection.
- Render every hosted non-connected Engine state as quiet, unactionable `Unavailable` while
  preserving exact local BYOK states.

### Test plan

- RED: `pending`, `error`, and `needs_reauth` must produce the exact same hosted Unavailable cell as
  `not_connected`, without availability source or raw wire vocabulary in repr.
- GREEN: connected hosted and all local BYOK presentation/control tests remain unchanged.
