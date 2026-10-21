# OME-1613 plan — `evaluate(pinned_cache=…)`, `score_id=`, `limit=` replay, submission metadata

Status: APPROVED by the owner 2026-10-21, prior-test option A.

Spec (approved 2026-10-21): `docs/spec/2026-10-20-OME-1613-evaluate-pinned-cache.md`.
Ledger: `docs/work/2026-10-20-OME-1613-evaluate-pinned-cache.md`. Stack: `screamingface`
(`packages/screamingface`), gates `uv run .claude/scripts/run_gates.py screamingface`.
Branch `OME-1613-evaluate-pinned-cache`, on `origin/main` at `ec4b632b2` (contains #1486).

One PR, one commit per row, RED first in each row. No Engine, gateway or scoreboard change.

## Rows

| # | Commit | Files | Tests (RED first) |
|---|---|---|---|
| 1 | Score reads for a replay | new `_scoreboard/replay_reads.py` (sync + async): `GET /v1/public/scores/by-pinned-cache/{id}` decoded to a small frozen `PublishedScore`; `GET /v1/public/scores/{id}`, falling back to the gated `GET /v1/scores/{id}` only on 404. Reuses `_decode_score`. `leaderboards.py` (1,141 lines) only gains two thin delegating methods. | Fake scoreboard transport: lookup 200 / 404; public read 200; public 404 → gated read; gated 404 → "unknown, malformed, private or never submitted"; a null `answer_seed` decodes to `None`, `0` stays `0`. Every assertion on parsed fields. |
| 2 | User-facing names | `report.py`, `leaderboard.py`: `pinned_cache` field; `frozen_copy_id` becomes a property that returns it and warns `DeprecationWarning`; `CandidateResult.reproduction: Reproduction \| None = None`. Saved-report JSON keeps the `frozen_copy_id` key, so old and new reports load both ways. | New field readable; alias warns and returns the same value; a report saved before and after round-trips (parsed JSON compared field by field). |
| 3 | Replay core | new `_replay.py`: argument checks (§3, §4a: seed `is None` rules, `url4.parse` equality, id match, `capture=True` refused), finding the score (§2), the full replay through `evaluate_url4_*` with `replay_frozen_copy`, the verdict via `_reproduction._classify`, recording after an exact verdict only, the S4 path with `reproduction=None`, and the all-cases-missed hint. `_reproduction.py` keeps `_classify`, `_record_*` and `Reproduction`. | §4a rows 1–11 one test each; ids mismatch; `score_id` alone; `capture=True` with a replay id; a bad url4 is a `ValueError`; S4 without url4 is a `ValueError` naming what to pass; hint only when every case has code `frozen_copy_miss` on the S4 path (a partial miss and a published score give none); recording only on `exact`, a login asked only then, `record_reproduction=False` records nothing; **invariant**: a fake transport asserts that no replay path sends a run without `X-Replay-Frozen-Copy`, and that every refusal happens before any request. |
| 4 | Entry points | `client.py` (Client and AsyncClient), `_default_client.py`: two replay `@overload`s each (`pinned_cache` required, `score_id` required) plus a runtime `TypeError` when neither candidates nor a replay id is given; route to `_replay.py`. `reproduce()` delegates to the same path and warns `DeprecationWarning: use sf.evaluate(pinned_cache=…)`. | Sync, async and module-level calls reach the replay; the empty call raises; a Pyright fixture file under `tests/typing/` must fail type-checking for `sf.evaluate()` and pass for both replay forms (checked by the existing pyright gate if the fixture is in its include path, else a test that runs pyright on it). |
| 5 | Partial replay | `_replay.py` (or `_replay_partial.py` if it passes 450 lines): `limit=n` rebuilds the url4 (§4): candidate text from the reference url4, the guard (rebuild at no limit; `url4.parse(rebuilt) == url4.parse(reference)`), then the `?limit=n` rebuild; `reproduction=None`, never recorded. | Guard passes and replays n cases; a revision change and a protocol change each refuse before any run with the "use a full replay" error; S4 reference is the caller's url4; `limit` never records and never classifies; `limit<=0` is a `ValueError`. |
| 6 | Submission metadata | `leaderboards.py` `submit` / `edit` (sync + async) gain `authors_metadata` and `paper_metadata`; type checks in a new `_scoreboard/credit_metadata.py`. Edit keeps the `_UNSET` sentinel: omitted preserves, `None` clears (OME-1596 semantics). | Payload asserted as parsed JSON field by field for submit and edit; omitted vs `None` vs `{}`; a non-mapping or a non-str key is a `TypeError` before any request. |
| 7 | Docs in the package | `CHANGELOG.md`, the SDK README section on reproduction, docstrings; notebooks regenerated only if their output changes (`check_notebooks`). Public docs are `OME-1614`, not this PR. | `check_notebooks` and `check_distribution` gates. |

## Prior tests (needs owner approval — SDLC rule 5)

`pyproject.toml` turns every `DeprecationWarning` from `screamingface` into an error
(`filterwarnings = ["error::DeprecationWarning:screamingface"]`). Deprecating `sf.reproduce` and
`frozen_copy_id` (S7, S8) therefore fails the prior tests that call them. Affected (2026-10-21):
`tests/test_capture_submission.py`, `test_capture_summary.py`, `test_frozen_copy_evaluate.py`,
`test_frozen_copy_transport.py`, `test_leaderboards_reproductions.py`, `test_reproduce.py`,
`test_reproduce_review.py`. Separately, `tests/public_surface_snapshot.json` pins the public API
and must gain the new names (`pinned_cache`, `reproduction`, the new parameters); that is an
additive snapshot update, listed in the same approval file. The two `tests/data/report_v1_*.json`
fixtures only carry the `frozen_copy_id` JSON key, which stays, so they do not change. Options:

- **A (proposed):** in those tests only, wrap each deprecated call in
  `pytest.warns(DeprecationWarning)`, or switch a pure field read to `pinned_cache`. No assertion
  is removed or loosened; wrapping adds one (the warning). The exact files and lines go into
  `.claude/test-change-approvals/OME-1613.json` for the append-only gate.
- B: add one narrow `ignore` entry to `filterwarnings` for these two messages. No prior test
  changes, but it hides the warnings in every test, including new ones.
- C: don't warn (drops S7/S8's warnings).

## Order and gates

Rows 1→7 in order; each row runs the full `run_gates.py screamingface`. Before the PR:
`run_gates.py repo`, a self-review, and the ledger outcome.

## Release (owner)

After merge: the next SDK release (it contains #1486 and this PR). Then `OME-1655` (button on) and
`OME-1614` (public docs).
