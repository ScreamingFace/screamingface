# Leaderboards

Source: https://docs.screamingface.ai/sf-client/api/leaderboards

The public board: what it holds, and what a submission records.

A leaderboard is the public ranking for one benchmark. This page covers `Leaderboard` itself, alongside `LeaderboardInfo` for a board's identity, `LeaderboardEntry` for a ranked row, `LeaderboardBaseline` for a published number to measure against, and `LeaderboardScore` for the full record a submission creates. `ScoreMetadataEvent` is one row of a score's edit log, and `Reproduction` is the verdict attached to a replayed `CandidateResult`.

Note: Leaderboard values come from a separate service set by `scoreboard_url` on a [Client](sf-client-api-clients.md). The SDK creates `Reproduction` by comparing a replayed result with the published score. A local Scoreboard accepts `submit()` and `get_score()`; `edit()` and `metadata_events()` need the identity of a signed-in submitter and raise `LeaderboardError` (HTTP 401) without it.

```python
import screamingface as sf

client = sf.Client()
[(b.id, b.display_name) for b in client.leaderboards.list()][:3]
```

```
[('air_bench', 'AIR-Bench 2024'), ('arc_agi_2', 'ARC-AGI-2'), ('bbh', 'BIG-Bench Hard (BBH)')]
```

## Leaderboard

One board, returned by `client.leaderboards.get(benchmark_id, top=50)`. It holds the ranking and the published numbers side by side, so a submitted result can be read against what the literature reports.

| Name | Type | Meaning |
| --- | --- | --- |
| `benchmark` | `LeaderboardInfo` | Which board this is. |
| `entries` | `tuple[LeaderboardEntry, ...]` | The ranking, capped by the `top` argument. |
| `baselines` | `tuple[LeaderboardBaseline, ...]` | Published results imported for comparison, not submitted through the Client. |

## LeaderboardInfo

A board's identity, and what `list()` returns.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | The benchmark id this board ranks, including its variant. |
| `display_name` | `str` | The board's name. |
| `description` | `str | None` | What it measures. |
| `dataset_url` | `str | None` | Where the underlying dataset lives. |
| `created_at` | `datetime` | When the board was created. |

## LeaderboardEntry

One ranked row. Every entry carries the url4 that produced it, so any position on the board can be re-executed rather than taken on trust.

| Name | Type | Meaning |
| --- | --- | --- |
| `rank` | `int` | Position on the board. |
| `spec_id` | `str` | Identifies the candidate that produced the result. |
| `score` | `float` | The benchmark-native score it is ranked by: exactly what the benchmark's grading produced, fractional or negative included. |
| `total_questions` | `int` | How many cases the result covered. |
| `ran_with_providers` | `tuple[str, ...]` | Which providers served the run. |
| `url4` | `Url4` | The expression that produced it. Pass it to [evaluate()](sf-client-api-clients.md) for a fresh run that may incur provider costs. To replay the captured answers, use `evaluate(pinned_cache=...)` or `evaluate(score_id=...)`. |
| `submitted_at` · `submitted_by` | `datetime` / `str | None` | When it was published, and by whom where that is recorded. |
| `authors` | `tuple[str, ...] | None` | The ordered public credit line. Email domains are normally omitted; full addresses distinguish authors whose local parts collide. |
| `verified_by_screamingface` | `bool` | Whether ScreamingFace re-ran the entry and confirmed the score. |

## LeaderboardBaseline

A published result imported for comparison. Baselines are not submissions and carry no url4, because nobody ran them through this Client.

| Name | Type | Meaning |
| --- | --- | --- |
| `model_name` | `str` | What the published number is for. |
| `score` | `float` | The reported score. |
| `source` · `source_url` | `str` / `str | None` | Where the number was published. |
| `benchmark_id` | `str` | Which board it belongs to. |
| `id` · `imported_at` · `metadata` | `UUID` / `datetime` / `Mapping | None` | Identity, when it was imported, and anything else recorded with it. |

## LeaderboardScore

The stored record a submission creates, returned by both `submit()` and `get_score(score_id)`. It keeps more than the board shows: where an entry has a rank and a score, a score has the full provenance of the run behind it.

```python
# Without limit=, this is a paid run over every case of the benchmark.
report = client.evaluate(recipe, benchmark="ifeval")
score = client.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    authors_metadata={"alice@example.com": {"full_name": "Alice Smith"}},
    paper_metadata={"title": "Our ensemble", "url": "https://arxiv.org/abs/2601.00001"},
)
```

`submit(candidate_result, *, authors=None, paper_url=None, authors_metadata=None, paper_metadata=None)` accepts one to ten email addresses in `authors`. A supplied list is exact: order and duplicates are preserved, and the authenticated submitter is not added automatically. Omit it to use the leaderboard's default credit line. `paper_url` is an `http` or `https` link of at most 2048 characters, with a host, no whitespace or control characters, and no user info.

`edit(score_id, *, authors=..., paper_url=..., authors_metadata=..., paper_metadata=...)` changes those fields of a score you submitted and returns the updated `LeaderboardScore`. An argument you leave out stays as it is, and you must pass at least one. `paper_url=None` removes the link. `authors` cannot be cleared: `authors=None` raises `ValueError`. `metadata_events(score_id)` returns the score's edit log, newest first, as a tuple of `ScoreMetadataEvent` values. Only the submitter can call either one. The [Leaderboards guide](sf-client-guides-leaderboards.md) shows them in use.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` · `version` | `UUID` / `int` | Identifies the stored score, and which revision of it this is. |
| `benchmark_id` · `spec_id` | `str` | What was evaluated, and against which board. |
| `score` | `float` | The benchmark-native score, exactly as submitted. |
| `total_questions` · `correct_questions` | `int` / `int | None` | How many cases ran, and, only for binary-graded benchmarks, how many were correct. |
| `url4` | `Url4` | The expression that produced the score. |
| `ran_with_providers` | `tuple[str, ...]` | Which providers served the run. |
| `ran_at_local` | `datetime | None` | When it ran on the submitter's machine. |
| `client_name` · `client_version` · `client_platform` | `str | None` | What submitted it, which matters when results disagree. |
| `submitted_at` · `submitted_by` | `datetime` / `str | None` | When it was published, and by whom. |
| `authors` | `tuple[str, ...] | None` | The ordered public credit line, using local parts unless full addresses are needed to distinguish authors. This is separate from `submitted_by`, which records who sent the result. |
| `verified_by_screamingface` | `bool` | Whether ScreamingFace re-ran it and confirmed the score. |
| `metadata` | `Mapping | None` | Anything else recorded with the submission. |
| `paper_url` | `str | None` | The link to the paper that reports the result, when one was set. |
| `authors_metadata` | `Mapping[str, Mapping[str, object]] | None` | Immutable metadata for each author, keyed by their public author identifier. Usually the email's local part; full addresses disambiguate matching local parts. Submit and edit use full email addresses instead. |
| `paper_metadata` | `Mapping[str, object] | None` | Immutable paper metadata, with `url` filled from `paper_url`. `None` when no object is stored; `{}` is an empty object. |
| `metadata_updated_at` | `datetime | None` | When the authors, paper link or metadata last changed. `None` if never. The portal shows it as "Metadata edited <date>" next to the paper link. |
| `scoreboard_url` | `str | None` | The Scoreboard that stored the score. |
| `ranking_notice` | `LeaderboardRankingNotice | None` | Why the score does not enter the ranking. `None` when it does. |
| `reproduction_count` · `last_reproduced_at` | `int` / `datetime | None` | How many exact reproductions the board stored for the score, and when the latest one ran. `last_reproduced_at` is `None` when the count is 0. |
| `pinned_cache` | `str | None` | The id of the pinned cache that the run made. `None` when the run was not captured. |
| `capture_status` | `"complete" | "partial" | None` | Whether the pinned cache holds the whole run. `"partial"` scores cannot be replayed. A local capture is always `"partial"`. `None` means unknown. |
| `case_digest` | `str | None` | A digest of the graded cases of the run: 64 lowercase hex characters. It is set only with a `capture_status`. `LeaderboardEntry` rows do not carry it. |
| `answer_seed` · `benchmark_revision` | `int | None` / `str | None` | The answer seed of the run and the revision of the benchmark it ran on. |

Boards that predate a field leave it absent, and it reads as `None`.

## LeaderboardRankingNotice

`LeaderboardScore.ranking_notice` explains why a successfully published score will not enter the current ranking, and is `None` when it will. A `LeaderboardRankingNotice` has a `code`, always `"benchmark_revision_mismatch"`, the `submitted_benchmark_revision` and the `registered_benchmark_revision` of the board.

## ScoreMetadataEvent

One row of a score's edit log, returned by `metadata_events(score_id)`. Each change to the authors, paper link or metadata writes one row. The log can hold author emails that were removed on purpose, so it is not public: only the submitter and the board's operators can read it.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Identifies the log row. |
| `edited_by` · `edited_at` | `str` / `datetime` | Who made the change, and when. |
| `source` | `"patch" | "resubmit"` | `"patch"` for an `edit()` call, `"resubmit"` for a resubmission that changed the fields. |
| `old_authors` · `new_authors` | `tuple[str, ...] | None` | The credit line before and after. |
| `old_paper_url` · `new_paper_url` | `str | None` | The paper link before and after. `None` means no link. |

## Reproduction

The verdict on `report.candidates.only.reproduction` after `client.evaluate(pinned_cache=…)` or `client.evaluate(score_id=…)`. The same calls work with `AsyncClient` (awaited) and module-level `sf.evaluate`. A partial replay or a capture without a public score has `reproduction=None`. A partial or unknown published capture, or an Engine that does not acknowledge replay, raises `ReproductionError`; its `.reproduction` carries the verdict. The [caching page](learn-caching.md) explains how a pinned cache is made and replayed.

```python
replay = client.evaluate(score_id=score.id)
result = replay.candidates.only
if result.reproduction is not None:
    print(result.reproduction.outcome, result.reproduction.reason, result.reproduction.recorded)
```

| Name | Type | Meaning |
| --- | --- | --- |
| `outcome` | `sf.ReproductionOutcome`, one of `"exact"`, `"failed"` or `"not_reproducible"` | `"exact"`: the replay gave the stored score and case count on the same benchmark revision, and the same case digest when the score has one. `"failed"`: it ran, or tried to, and did not match. `"not_reproducible"`: the score has no complete pinned cache, so no run started; this outcome is carried by `ReproductionError`. |
| `reason` | `str | None` | Why the outcome is not exact. `None` when it is exact. See the table below. |
| `missed_cases` | `tuple[int | str, ...]` | The ids of cases the pinned cache could not answer. Filled only when `reason` is `"frozen_copy_miss"`. |
| `recorded` | `bool` | Whether the board stored this exact reproduction. |
| `record_error` | `str | None` | Why an exact replay could not be recorded. The outcome stays `"exact"`. |

The Client checks a replay in this order and reports the first problem. A score that is not reproducible starts no run, so its reason comes before any replay. A missing or unavailable copy is checked before a failed run, because a run that missed the copy has nothing to compare.

| `outcome` | `reason` | Meaning |
| --- | --- | --- |
| `not_reproducible` | `partial` | The score is `capture_status="partial"`. A local capture also gets this reason: the board does not store the partial reasons, so the reason is never `local`. No run starts. |
| `not_reproducible` | `unknown` | The score has no `capture_status`, no `pinned_cache` or no benchmark revision. No run starts. |
| `failed` | `replay_unsupported` | The Engine did not confirm replay mode. When the Engine did not echo the replay at the start, the Client stopped the run. If the stop failed, an `EvaluationWarning` says the run may still be running and spending. An Engine can also confirm the start and then finish a run whose summary does not name the copy. That run is already over and may have called providers. The Client does not report it as a replay. |
| `failed` | `frozen_copy_miss` | The copy had no answer for some calls. `missed_cases` lists their cases. The replay bought nothing. |
| `failed` | `frozen_copy_unavailable` | The copy is unknown or not sealed, or the gateway has no pinned caches (an older gateway), or the gateway did not serve a model call or a web-tool lookup of the replay. The cases fail, and the run finishes. |
| `failed` | `run_failed` | The replayed run itself failed, and the cause is not a missing copy. |
| `failed` | `benchmark_revision_changed` | The benchmark is now a different revision, so the numbers cannot be compared. A changed benchmark can also show as `frozen_copy_miss`, which is checked first. |
| `failed` | `score_differs` | The score or the case count is not the stored one. The comparison is exact. |
| `failed` | `cases_differ` | The score and the case count match, the score has a `case_digest`, and the replay's digest is not the stored one. |

Only an `"exact"` full replay is recorded, and only when `record_reproduction=True` (the default). A failed record never changes the outcome.

Pass `score_id` as a `UUID` or string, not a `LeaderboardScore`. Bad argument types raise `TypeError`; conflicting ids, recipes or seeds raise `ValueError`. The Client reads the published score first, and that read raises [`LeaderboardError`](sf-client-api-errors.md) if it fails. `replay_unsupported` becomes `ReproductionError`; other `ExecutionError` instances propagate. When the Client cannot stop a run that the Engine did not confirm as a replay, it emits an `EvaluationWarning`. The [caching page](learn-caching.md) explains what makes a score `"partial"`.

A leaderboard call that cannot be completed safely raises [LeaderboardError](sf-client-api-errors.md).
