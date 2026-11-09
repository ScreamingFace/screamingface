---
ticket: OME-1809
stack: screamingface-engine
status: planned
started: 2026-11-09
finished:
---

# blind-model-admission — refuse a url4 run's attachments for models that can't read them, before any call

## Intent

OME-1551 F4: a url4 ensemble over an image calls and bills its capable members, then fails on the
text-only member's provider 404. Admission (OME-1548 / OME-1803) only guards the Benchmark Cases
route. Extend it to every url4 run that carries frozen attachments (#1587 / #1588), so a blind
model is refused by name before any chat call. Spec: `docs/spec/2026-11-09-blind-model-admission.md`.

## Planned changes

- `benchmarks/picture_admission.py` — a run-scoped, once-per-run admission over the frozen list.
- `world/connector.py` — `call_model` awaits that admission before building parts.
- Tests under `apps/screamingface-engine/tests/` (RED list in the spec §6).

## Test plan

- See spec §6.

## Acceptance

- Ticket OME-1809 acceptance, verbatim; Benchmark-route admission unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
