---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# parked-case-results — park each Case of the Candidate Result on disk (unit 2 of memory fix 3)

## Intent

Unit 1 (OME-1835, PR #1855) removed the whole `str`, url4 copy and bytes copy of the Candidate
Result. The peak that remains is the list of full `CaseResult` objects that the aggregate holds
while it marks, finalizes and writes the result (about 30 KiB per Case for a 5-member Fusion).
This unit parks each Case's wire JSON in the run's Case-result store as it is marked, scores on
light projections, and writes the result body from the parked text. The bytes on the wire and
the SDK contract do not change. The goal is aggregate memory that is flat in the Case count.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md` ("Unit 2 — parked Cases").
Plan: `docs/plan/2026-11-16-streamed-candidate-result.md` ("Unit 2 — parked Cases").

This branch is stacked on `OME-1835-streamed-result-delivery` (unit 1, not merged yet). It is
rebased onto `origin/main` when PR #1855 merges.

## Planned changes

See the plan, "Unit 2 — Files". One correction to the plan: unit 1's `deliver_result` and
`deliver_result_sync` accept only a `CandidateResult`, so they must also accept a `ResultBody`
(the `ParkedResultBody`). The writer and the spool do not change.

## Test plan

See the plan, "Unit 2 — TDD order". Score identity first, on today's code. The invariant under
test: the delivered bytes equal unit 1's bytes, and every score equals today's score.

## Acceptance

- Engine gates green; all existing aggregate tests unchanged.
- Aggregate growth per Case is flat between N=500 and N=2,000, and is a small multiple of one
  projection. The stage tables below, measured again after the change.

## Baseline measured before the unit (2026-11-16, unit 1 at `5a1260b49`)

`scripts/bench/report_memory.py`, tracemalloc, peak KiB per Case above the start of the
aggregate; synthetic MMLU-Pro, stub gateway. Gates green (`--base
origin/OME-1835-streamed-result-delivery`); inspect lane 3,046 passed.

| Stage | 1 model N=500 | 1 model N=2,000 | Fusion N=500 | Fusion N=1,000 | Fusion one emoji N=300 |
|---|---|---|---|---|---|
| Candidate Result bytes | 3.8 | 3.8 | 9.9 | 9.9 | 9.9 |
| `CaseResult` list held (marking done) | 10.9 | 10.5 | 31.4 | 30.9 | 31.0 |
| + finalize (peak of the run) | 11.7 | 11.6 | 32.4 | 32.0 | 31.7 |
| spool delivered | 11.6 | 11.5 | 32.3 | 31.9 | 31.6 |
| held until the run ends | −1.6 | −1.7 | −2.0 | −2.4 | −2.8 |

The peak is the full `CaseResult` list: about 3 × the result bytes per Case.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
