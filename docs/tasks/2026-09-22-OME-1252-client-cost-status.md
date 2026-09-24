---
id: OME-1252
linear_url: https://linear.app/openmined/issue/OME-1252/send-the-run-cost-its-status-and-the-cache-saved-cost-totals
status: in_review
type: task
priority: high
labels: [py-screamingface, agentic, autonomous]
parent: OME-1251
created: 2026-09-21
closed:
---

# Send the run cost and its status

Client half of epic `OME-1251`; the Scoreboard half is `OME-822`. PR `#930` made the engine
measure what each cache hit avoided, per span, with provenance, and the SDK dropped it at the
parser. This unit reads it and tells the board what the submitted amount is worth.

Ledger: `docs/work/2026-09-22-OME-1252-client-cost-status.md`.
Spec: `docs/spec/2026-09-22-OME-1252-client-cost-status.md`.
Plan: `docs/plan/2026-09-22-OME-1252-client-cost-status.md`.

**Ships second.** `ScoreSubmission` is `extra="forbid"`, so `OME-822` must be deployed and
confirmed live before this is released. `packages/screamingface` is on release-please, so the
gate is on the release PR, not on this one.

- 2026-09-21: filed as the Client half of `OME-1251`, carrying decisions D1-D4. Scope already
  cut once at filing: the per-provenance hit counters (`reported_hits`, `archive_hits`,
  `unpriced_hits`) are not on `SpanData` and exist only as engine log attributes, and a `Log` is
  the one event kind the engine drops under backpressure. A published cost cannot ride a
  droppable frame. Accepted consequence: `unavailable` conflates "no cache hits" with "hits
  nobody could price".
- 2026-09-22: **scope corrected before any code.** The ticket asked for the two saved-cost sums
  to be sent as well. That would 422 every submission — `OME-822` added exactly one field to the
  board, `run_cost_status`, and `ScoreSubmission` is `extra="forbid"`. Verified by grep against
  the `OME-822` head. The sums are still read and still essential, because they are what
  separates `partial` from `unavailable`, but they stay client-side and feed the derivation
  rather than the wire. Nothing on the board would read them today: D2 keeps an unpriced row off
  every cost surface whatever the reason, and D3 already decided `archive_matched` money is not
  published.
- 2026-09-22: RED -> GREEN complete on `OME-1252-client-cost-status` from `origin/main` at
  `51e908d8`. `events.Span` gains the two saved-cost amounts; `_engine/contract.py` parses and
  accumulates them as two separate sums; `RunOutcome` carries both; `_evaluation/results.py`
  derives `run_cost_status`; `_scoreboard/leaderboards.py` sends it. Gate runner ALL GREEN, 95%
  coverage, 9 new tests in `tests/test_run_cost_status.py`. Two owner-approved exceptions: the
  payload key-set guard in `tests/test_leaderboards.py` gains one string, and the public surface
  snapshot is regenerated (7 lines, all cost-related). Committed `5149f59a`. **Gate:** in review.
