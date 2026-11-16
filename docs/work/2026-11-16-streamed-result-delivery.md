---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: planned   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# streamed-result-delivery — deliver the Candidate Result without building it whole (unit 1 of memory fix 3)

## Intent

Large runs are killed with `memory_budget_exceeded` right after the last Case (`OME-1885`:
5-model Fusion on full MMLU-Pro, 2,926 MB; `OME-1887`: production blocker). The end of a run
builds the whole Candidate Result as a dict tree, one `str`, a url4 copy of that `str` and a
bytes copy. With one wide character in any answer the `str` is 4 bytes per character, and the
peak is 8 × the result bytes. This unit streams the result one Case at a time into an artifact
sink and passes a small reference through url4. The bytes on the wire and the SDK contract do
not change. Unit 2 (parked Cases) follows after this unit's numbers.

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md`.
Plan: `docs/plan/2026-11-16-streamed-candidate-result.md` (units 0 and 1).

## Planned changes

See the plan, "Unit 1 — Files".

## Test plan

See the plan, "Unit 1 — TDD order". The invariant under test: the delivered bytes equal
`compact_json(CandidateResult.as_payload())` of the previous code.

## Acceptance

- Engine gates green; existing aggregate, result-delivery and e2e replay tests unchanged.
- The stage table below, measured again after the change: no dict-tree, `str` or bytes stage,
  and nothing result-sized held until the run ends.

## Baseline measured before the unit (2026-11-16, `main` at `4679d5c6a`)

tracemalloc, KiB per Case above the start of the aggregate; synthetic MMLU-Pro, stub gateway.

| Stage | 1 model, N=2,000 | 5 members + synthesizer, N=1,000 | same, one emoji in one answer, N=300 |
|---|---|---|---|
| Candidate Result bytes | 3.8 | 9.9 | 9.9 |
| `CaseResult` list held | 10.0 | 30.4 | 30.8 |
| + finalize | 11.3 | 31.6 | 31.8 |
| + dict tree | 14.3 | 39.1 | 39.2 |
| `str` + url4's copy | 8.1 | 23.5 | 77.6 |
| bytes + store write | 5.8 | 17.3 | 76.7 |
| held until the run ends | 2.0 | 7.3 | 37.0 |

Also checked: a result assembled one Case at a time, each Case through a JSON round trip, is
byte-identical to today's (120 Cases, 720 operations, 1,218,105 bytes).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
