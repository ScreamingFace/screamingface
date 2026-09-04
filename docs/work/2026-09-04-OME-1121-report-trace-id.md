---
ticket: OME-1121
stack: screamingface
started: 2026-09-04
status: in_progress
finished:
---

# OME-1121 — Surface the run's `trace_id` on the public result

## Intent

`OME-967` made the client mint a traceparent and send it on all three legs, but the id
reaches only the **error hierarchy**. A board run does not raise — DRACO fans out with
`on_error="collect"`, so case failures become rows and the run returns a `Report` normally.
The result is backwards from what the observability roadmap wants: the user whose run
produced *bad results rather than an exception* — the person most likely to file a report —
is precisely the one who cannot obtain an id to quote.

This is not theory. `test_correlation_chain.py::test_rung1_one_coherent_trace_id_spans_the_run`
(`OME-1105`) is a strict xfail for exactly this reason, and closing it is this unit's job.

First child of the Phase 1 epic (`OME-1118`) per
`docs/plan/2026-09-04-OME-1118-phase-1-signoz-validation.md` §5: it is independent of every
other item, and until it lands nothing downstream can be validated by a human end-to-end.

## Design decisions

**D1 — the id goes on `CandidateResult`, beside `run_id`; NOT on `Report`.** The ticket title
says "on Report", and that is the wrong shape. A `Report` holds a `_CandidateResults`
collection, and **each candidate is an independently executed run with its own
client-minted trace** — `CandidateResult` already carries a per-run `run_id` for the same
reason. A single `Report.trace_id` would be a lie the moment a report holds two candidates,
and there is no defensible way to pick one. One run, one trace, one field, next to the field
that already identifies that run.

The single-candidate case — which is the common one, and the one the notebook uses — reads
`report.candidates.only.trace_id`.

**D2 — no `Report.trace_ids` convenience, for now.** It was considered: a user pasting into
SigNoz with three candidates wants three ids. But it is a second public surface serving a
case nobody has hit yet, and `tuple(c.trace_id for c in report.candidates)` is one line at
the call site. YAGNI wins; add it when a real multi-candidate paste asks for it. Recorded so
the omission reads as a decision rather than an oversight.

**D3 — the value stays the id the CLIENT minted.** `_RunOutcome.trace_id` is stamped by the
transport (`OME-967`), deliberately not read back off a frame, so a user quoting it is
quoting what actually travelled — including for a run whose frames never arrived. This unit
only carries that value across the report-building boundary; it must not re-derive it.

**D4 — nullable.** `_RunOutcome.trace_id` is `str | None`, and a `Report` decoded from a
stored url4 replay (`report_from_url4_outcome`) has no live run behind it. Forcing a value
would mean inventing one.

## Planned changes

- `src/screamingface/report.py` — `trace_id: str | None` on `CandidateResult`, beside
  `run_id`.
- `src/screamingface/_evaluation/results.py` — pass `outcome.trace_id` through
  `_candidate_result`.
- `tests/public_surface_snapshot.json` — regenerated; additive public surface.
- `tests/e2e/test_correlation_chain.py` — rung 1 reads the report and its strict xfail is
  deleted. **This trips the append-only gate**, see below.

## Test plan

RED first:

- A `CandidateResult` built from an outcome carrying a trace id exposes it.
- The id on the result is the id the transport stamped — not one re-derived from a frame.
- A `Report` whose outcome has no trace id exposes `None` rather than raising (D4).
- Rung 1 of the e2e ladder passes: a completed run yields exactly one well-formed id,
  obtained from the public surface.

## Known process consequence — the ladder trips the append-only gate every time

Deleting a strict-xfail marker **is** modifying a prior test, so `run_gates.py` will flag
`test_correlation_chain.py` on this PR and on every rung PR that follows. That is inherent to
the ladder design from `OME-1105`: the marker deletion is the mechanism, and the mechanism is
a test edit.

It is a Confidence-Gate decision each time (rule 5). Worth deciding once whether the ladder
file should be exempted from that check rather than approving the same shape four more times
— raised here rather than silently re-approved.

## Acceptance

- A completed run's trace id is reachable from the public API.
- Rung 1 passes; rungs 2, 3, 4a, 4b stay strict xfails.
- Public surface additive only; no prior test weakened.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the e2e fixture fix — `report.py`,
  `_evaluation/results.py`, `tests/test_report.py`, `tests/e2e/test_correlation_chain.py`,
  `tests/public_surface_snapshot.json`, ledger + mirror.
- **Commits:** `feat(screamingface): carry the run's trace id onto the candidate result`
  (sha at squash-merge).
- **Gates:** `run_gates.py screamingface --skip-append-only` — **ALL GATES GREEN**: ruff,
  ruff format, pyright, `pytest --cov --cov-fail-under=95`, check_notebooks, uv build,
  check_distribution. The ladder: **1 passed, 4 xfailed** — rung 1 flipped green, and the
  remaining rungs still fail as designed.
- **Deviations:**
  - **The e2e fixture named a model the synthetic tape does not carry, and that was masking
    everything.** `openrouter/anthropic/claude-haiku-4.5` is absent from the tape's catalog
    projection, so `evaluate` raised `PlanningError` in the availability probe
    (`runner.py::_missing_required_models`) **before the transport ran**. No transport means
    no trace context, so every rung read an empty id set and rung 1 could not pass no matter
    what this unit did. Confirmed by probe:
    `RAISED PlanningError | trace_id = None | "Model ... is not available on this Engine"`.
    Changed to `openrouter/openai/gpt-5.5`, which the tape carries. **This was a defect in
    `OME-1105`'s fixture, surfaced only by trying to make its rung pass** — the ladder was
    reporting a real absence for the wrong reason.
  - **`to_dict()` does NOT gain the field.** `CandidateResult.to_dict()` carries `run_id`,
    and the exported artifact arguably should carry the trace id too — it is the "attach this
    to a report" surface. But `to_dict` output is compared against e2e **golden fixtures**,
    which are prior tests, so changing it risks a regression outside this unit's scope for a
    benefit the ticket does not require. Left as a follow-up, deliberately.
  - **The `wire_run` fixture was refactored** to extract `_one_run`, because adding the
    report-reading branch pushed it past ruff's `PLR0915` statement limit. The gate was
    satisfied by restructuring, never by suppression.
  - Rule 5 Confidence-Gate: three test files flagged; approved by the owner on the numbers —
    assertions **12 → 12**, test functions **5 → 5**, one xfail marker deleted, and
    `test_report.py` purely additive (+47, 3 new tests, 0 removed).
