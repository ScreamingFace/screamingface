# OME-1613 — `evaluate(pinned_cache=…)` and submission metadata in the SDK

Status: APPROVED by the owner 2026-10-21. Owner design review (grilling) settled 2026-10-21; every decision is
in §6. Ticket decisions S1–S9 are binding except where §6 records an owner change.

## 1. Public API

```python
sf.evaluate(candidates, *, benchmark=None, limit=None, answer_seed=None, capture=None, ...)  # today
sf.evaluate(*, pinned_cache: str, score_id: str | None = None, url4: str | None = None,
            answer_seed: int | None = None, limit: int | None = None,
            record_reproduction: bool = True, on_event=None, progress=None) -> Report
sf.evaluate(*, score_id: str, pinned_cache: str | None = None, url4: str | None = None,
            answer_seed: int | None = None, limit: int | None = None,
            record_reproduction: bool = True, on_event=None, progress=None) -> Report
```

- Two new `@overload`s, one per required id, so Pyright rejects a call with neither candidates nor a
  replay id (Q5, R4). A runtime `TypeError` backs them up. Same on `AsyncClient.evaluate` and the
  module-level `sf.evaluate`.
- A replay call takes no `candidates`, no `benchmark=` and no `capture=True` (S6: a replay records
  nothing; an explicit `capture=True` with a replay id is an error).
- `CandidateResult` gains `reproduction: Reproduction | None`. On `CandidateResult` and
  `LeaderboardScore` the field `frozen_copy_id` is **renamed** to `pinned_cache`, with no alias
  (owner, 2026-10-21, Q12). Saved-report JSON and every wire name keep `frozen_copy_id`, so old
  report files still load.
- `submit(..., authors_metadata=None, paper_metadata=None)` and
  `leaderboards.edit(score_id, ..., authors_metadata=..., paper_metadata=...)` send both fields as
  plain JSON objects (S9). The scoreboard (OME-1596) owns keys, bounds and matching; the SDK checks
  only the types (mapping of str → mapping or scalar), so a typo fails before the request.
- `sf.reproduce` and `Client.reproduce` / `AsyncClient.reproduce` are **removed** (owner,
  2026-10-21, Q13). `sf.evaluate(score_id=…)` replaces them; `record=` becomes
  `record_reproduction=`. The CHANGELOG lists both under Breaking, with the replacement.

## 2. Finding the published score

| Call | Read | Login |
|---|---|---|
| `pinned_cache` only | `GET /v1/public/scores/by-pinned-cache/{id}` | none |
| `score_id` (with or without `pinned_cache`) | `GET /v1/public/scores/{id}`; on 404, the gated `GET /v1/scores/{id}` | only for a private score (Q3, R2) |

- With `score_id`, the public lookup by cache id is skipped (Q8).
- With both ids, the score's copy id (`frozen_copy_id` on the wire, `pinned_cache` in the SDK) must
  equal `pinned_cache`, else `ValueError` before any run (Q8). With `score_id` alone, `pinned_cache`
  is the score's copy id.
- Both public reads answer the same 404 for unknown, malformed, private and never-submitted ids, by
  design. The error text names all four.
- Checked on production 2026-10-21: the public score read returns `frozen_copy_id`, `capture_status`,
  `case_digest`, `url4_expression`, `score`, `total_questions` and `benchmark_revision`. Both
  captured production rows have no `answer_seed`; the field is omitted when null (§4).

**No published score (S4, Q7 kept):** if the lookup answers 404 and no `score_id` was given, the
caller must pass `url4`. The replay then runs with the given `url4` and `answer_seed` and returns
`reproduction = None` ("no published score to compare"). Nothing is recorded.

## 3. Checks before any run

All of these run before a token is minted or a run is scheduled.

1. `capture_status == "partial"` → no run; raises `sf.ReproductionError` with code
   `not_reproducible`, reason `partial`. A score with no copy id, status or revision → the same
   error with reason `unknown`. An Engine that refuses replay raises it with code
   `replay_unsupported`. The error carries the `Reproduction` (Q14): a `Report` always means a run
   happened.
2. **Seed (S2):** a passed `answer_seed` must equal the score's. A score with no seed means the run
   had none; passing one is then a mismatch error, because a stamped seed changes every request.
3. **Recipe (S3, Q2):** a passed `url4` must be the same parsed recipe:
   `url4.build(passed) == url4.build(published)`. `url4.build` is the url4 package's public parser; its AST is frozen dataclasses, so
   equality is structural. A `url4` that does not parse is a `ValueError`. Limit (Q6, accepted): the parser
   keeps an inline `{…}` object as raw text (`StructObject.raw`), so key order or spacing inside one
   still counts as a different recipe. The docs say so. Omitted → the published url4.

## 4. Replay

**Full replay:** the published (or passed) url4 runs through `evaluate_url4_*` with
`capture=False`, `replay_frozen_copy=<id>` and the score's `answer_seed` (none if the run had none),
as `_reproduction._replayed_*` does today. The Engine answers every call from the copy or fails the
case, so a replay costs no provider spend. A run the Engine does not acknowledge as a replay is
stopped (`_require_replay_statement`).

**Partial replay, `limit=n` (Q4, Q9, Q10):** the first n cases in benchmark file order (case ids
1..n), the same meaning as a normal `evaluate(limit=n)`. Feasibility (research 2026-10-21, cited in
the ledger): a copy's replay key is the case id and Attempt; the case count is stripped before the
model input; nothing compares the url4 against the copy. So no Engine or gateway change is needed,
but the url4 cannot be edited in place (n appears in four or more places that vary by benchmark).
The SDK rebuilds it:

1. Take the candidate text out of the reference url4 (`_candidate_text(build(url4))`). The reference
   is the published url4, or the caller's `url4` on the S4 path (R3).
2. **Guard:** fetch `GET /v1/benchmarks/{id}` with no limit, bind the candidate, and require
   `url4.build(rebuilt) == url4.build(reference)`. The revision is in every route path, so this
   also checks the revision. On a mismatch, refuse before any run: "this Engine can no longer
   rebuild that run; use a full replay".
3. Fetch `?limit=n`, bind the same candidate, and run it as a full replay would.
4. The result is never judged: `reproduction = None` ("subset, not judged"). Never `exact`, never
   recorded.

## 4a. Seeds

How the seed works: a run's `answer_seed` is optional. When set, the Engine stamps `seed=<n>` on
every model call that does not state its own seed (`world/request_parameters.py`
`apply_answer_seed`); when not set, it stamps nothing. Attempts 2+ of a seeded run derive their seed
from it; Attempts of an unseeded run carry no seed and are told apart by the Attempt number. The
seed is part of the request, so it is part of the request digest the copy is keyed on: replaying
with another seed, or with one where the capture had none, misses every call. The board omits a
null seed from its JSON. `0` is a seed: the code tests `is None`, never truthiness.

**With a published score** (`pinned_cache` lookup, `score_id`):

| # | Board seed | Caller passes | Result |
|---|---|---|---|
| 1 | 42 | nothing | Replays with 42 (S2) |
| 2 | 42 | 42 | Replays with 42 |
| 3 | 42 | 7 | `ValueError` before any run |
| 4 | none | nothing | Replays with no seed (both captured production rows, 2026-10-21) |
| 5 | none | 7 | `ValueError` before any run |
| 6 | 0 | nothing | Replays with seed 0 |

**Without a published score** (S4: lookup 404, caller passes `url4`). Nothing to check against
before the run:

| # | Capture had | Caller passes | Result |
|---|---|---|---|
| 7 | 42 | 42 | Replays; `reproduction = None` |
| 8 | none | nothing | Replays; `reproduction = None` |
| 9 | none | 42 | Every case fails `frozen_copy_miss`, at $0 |
| 10 | 42 | nothing | Same as 9 |
| 11 | 42 | 7 | Same as 9 |

**Hint for rows 9–11 (owner, 2026-10-21):** on the S4 path only, when every case of the replay
failed with the error code `frozen_copy_miss`, the SDK raises one `EvaluationWarning` (there is
no verdict on this path to carry a hint, so the warning is the hint):
"no case was found in the pinned cache; check that `answer_seed` and `url4` are exactly the
captured run's (a run captured without a seed must be replayed without one)". The condition is
structural (no published score, and the code of every case's failure), never a match on error
text. A partial match (some cases miss) gets no hint: that is a real copy miss, not a seed mismatch.

**Partial replay (`limit=n`):** the same rules as rows 1–11 on the first n cases; the seed does not
depend on n.

**Attempts and per-call seeds:** a seeded run's Attempts 2+ derive the same seeds on replay; an
unseeded run's Attempts match by Attempt number; a call that states its own seed (the draco judge)
keeps it on both sides. All three match the copy.

**Later (owner agreed we can do better, not in this ticket):** tell the caller up front whether a
copy was captured with a seed, so rows 9–11 fail before the run. It needs the gateway to answer that
one fact for a copy without returning stored requests (E14 B1 rule), so it is a gateway change.

## 5. Verdict and recording

- **Verdict (full replay with a published score):** today's pure `_classify` (copy miss, unavailable
  copy, run failure, revision, score and case count, case digest). A failed replay reports
  `outcome = "failed"`, a `reason` (`score_differs` / `cases_differ` / `frozen_copy_miss` / …) and
  `missed_cases`, the cases the copy could not answer. There is no list of *differing* cases: the
  board stores only a digest of the case results (Q2). Per-case results on the board are a
  follow-up.
- **Recording (S5, Q1, R1):** an `exact` verdict is recorded on the board unless
  `record_reproduction=False`. The login is asked for only then: a `pinned_cache` replay needs no
  login before or during the run. A `score_id` read of a private score has already asked for the
  login before the run, and recording reuses it. A login is asked for at most once per call. The login completes since PR #1486
  (OME-1649) returns it to the challenged path. A failure to record never fails the replay; it is
  reported on `reproduction.record_error` (today's behaviour).

## 6. Decisions

| # | Topic | Decision |
|---|---|---|
| Q1 | Login for recording | After an exact verdict only. |
| Q2 | Differing cases | `reason` plus `missed_cases`; the ticket's "`differing` case ids" acceptance line is replaced; a follow-up for per-case results is filed. |
| Q3 | Private score owner | `score_id=`, read as in §2. |
| Q4 | Partial replay | `limit=n` allowed; never judged, never recorded. |
| Q5 | Types | `@overload`s for the replay forms, plus a runtime check. |
| Q6 | `{…}` hole | Accepted and documented. |
| Q7 | S4 | Kept. |
| Q8 | `score_id` rules | Mismatch is an error; `score_id` alone is allowed; with `score_id`, no public lookup by cache id. |
| Q9 | Partial-replay guard | The full rebuild must equal the reference recipe, else refuse. |
| Q10 | Case choice | First n only. |
| R1 | Q1 wording | A `pinned_cache` replay needs no login; at most one login per call. |
| R2 | `score_id` read | Public read first, gated only on 404. |
| R3 | Guard reference | Published url4, or the caller's url4 on the S4 path. |
| R4 | Overloads | One per required id (`pinned_cache` or `score_id`). |
| — | No seed | A score without a seed replays with none; passing one is a mismatch (§3). On S4, `answer_seed` is needed only if the run had one. |
| Q11 | S4 seed mismatch (§4a rows 9–11) | Hint and warning when every case misses on the S4 path; an up-front check is a later gateway change. |
| Q12 | Old field name | Hard rename `frozen_copy_id` → `pinned_cache` in the Python API, no alias (feature one week old, SDK pre-1.0). Wire and JSON keep `frozen_copy_id`. Replaces S7's deprecated alias. |
| Q13 | `sf.reproduce` | Removed now; `sf.evaluate(score_id=…)` replaces it. Replaces S8's deprecation. |
| Q14 | No run, no Report | A replay that cannot start (capture `partial` / unknown, or an Engine that refuses replay) raises `sf.ReproductionError` carrying the `Reproduction`, like the other pre-run refusals. |

## 7. Invariants

- No replay path schedules a run without `X-Replay-Frozen-Copy`. A replay never spends.
- All argument checks and the partial-replay guard run before any token is minted or run scheduled.
- Every comparison is structural: parsed url4 ASTs, parsed JSON fields. No substring or regex checks.
- Internal names stay `frozen_copy` (wire, Engine headers, gateway). Only user-facing names change.

## 8. Release

- OME-1596 (PR #1440) is live in production (smoke-checked 2026-10-20).
- The release is a **breaking** minor version (Q12, Q13): `frozen_copy_id` is `pinned_cache` in the
  Python API and `sf.reproduce` is gone. The CHANGELOG lists both under Breaking with the
  replacement (`sf.evaluate(score_id=…)`, `record_reproduction=`). The public docs that teach
  `sf.reproduce` or `frozen_copy_id` (four pages under `public-docs/src/pages/`) are rewritten in
  `OME-1614`, which ships with or right after this release.
- The release must also contain PR #1486 (OME-1649), or recording and submit hang on the production
  login. SDK 0.1.5 (released 2026-10-20 from `0fb6f20be`) does not.
