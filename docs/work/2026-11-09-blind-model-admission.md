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

## Progress

- 2026-11-09: spec approved (Q1–Q3 = a); plan `docs/plan/2026-11-09-blind-model-admission.md` (9 TDD tasks, 3 code-forced deviations flagged).

## Test plan

- See spec §6.

## Acceptance

- Ticket OME-1809 acceptance, verbatim; Benchmark-route admission unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
- Implementation (2026-11-09): T1–T8 + T10 (OME-1770 masking, from security review) committed
  locally (cf74524d4, 10b1977d5, 7be52a61c, a6173f057); `test_run_attachment_admission.py`
  15 passed. Deviation from plan: the default processor counts only when a group FANS OUT
  (url4 `_wiring._reduce_graph`: every source a relative-expression call, one contributing) —
  a literal-Text intent alone merges locally via `default_process` and calls no model. Handler
  slots unchanged (reader built per admission from world-level fields) to keep
  `test_request_scope_hardening` untouched.
- BLOCKED on owner approval: `tests/unit/test_fair_share_fetch_bytes.py::
  test_a_gate_bound_run_with_an_https_attachment_reaches_the_model` — its mock gateway answers
  `/v1/models` with a chat body, so the fail-closed admission now refuses the run retryably.
  Needs an approved amendment (mock serves `/v1/models` listing `MODEL` with `["text","image"]`).
  Engine gate: 1 failed / 8014 passed.
