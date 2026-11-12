# Leaderboard

Source: https://docs.screamingface.ai/learn/leaderboard

The public board where ensemble results are ranked, and where every entry carries the recipe that produced it and whether the hosted engine ran it.

The **Leaderboard** is where results go public. It ranks ensemble runs against research benchmarks, and each entry says whether the hosted engine ran it (`verified_by_screamingface`). Every entry shows what it scored, what it cost to get there, and the [url4](learn-url4.md) expression that produced it, which is what you would use to run the same evaluation and check the number against your own result.

[Diagram: The engine submits a verifiable result, the score together with the reproducible url4 recipe, to the public leaderboard.]

A rank is a verifiable submission: the score together with the url4 recipe that reproduces it.

Published model numbers usually originate with the party that benefits from them, and are reported rather than demonstrated. The board is organized around the opposite arrangement: a rank is a claim the hosted engine has run itself, and that you can run again from its url4.

A run made with `capture=True` keeps a pinned cache of its model answers and web-tool results, and `sf.evaluate(pinned_cache="…")` replays a submission against that cache. The Reproduce button on a captured public row copies this snippet. The Client reads the recipe and seed from the board and returns a report; its single result's `reproduction.outcome` says whether the full replay is exact. The [caching page](learn-caching.md) explains how.

## How a rank happens

A submission carries the benchmark, the recipe's url4, the result, and the providers the run used. It then goes through four steps before it appears:

-   **Validation:** The score is benchmark-native: the exact number the benchmark's own grading produced, fractional or negative included. The board checks it is a finite number and never recomputes, normalizes, or thresholds it; the benchmark is the sole authority on its formula.
-   **Deduplication:** Each submission is hashed over its recipe identity, meaning the benchmark, the spec, the expression, the result, and the providers. Identical content lands on the same entry rather than a second one. A resubmission inside a 24-hour idempotency window replays the original instead of creating a duplicate.
-   **Verification:** `verified_by_screamingface` is a property of the engine that ran the submission: a run on the hosted engine is verified. A submission from a run on any other engine stays unverified until the hosted engine also runs it. It is the flag worth reading before you trust a row.
-   **Ranking:** The board keeps the best result per spec, ties broken by recency, and orders by score, descending. One recipe cannot crowd the board with near-identical attempts.

## The line to beat

Single-model results imported from public sources can sit on the same board as the ensembles, as **baselines**; `board.baselines` is an empty tuple on a board that has none, such as `draco-3pass`. They are what makes a fusion's gain legible: a composed system is only interesting if it beats the models it is composed from, and the comparison should use numbers the field already accepts. Each baseline records where it came from, so you can go read the original.

## The paper link

A submitter can link the paper that reports a result. The submitter can also change the authors and the paper link later. The portal shows "Metadata edited <date>" next to the paper link. The date is the last time either field changed. The edit log of a score is not public.

## The recipe is the reward

A rank on its own would only settle who is ahead. What makes the board compound is that the recipe travels with it: every entry stores its url4, so the ordinary way to enter is to start from whatever is currently winning, change one part of it, and run it again. Prior results become the starting position rather than a blank file.

A call already in the [cache](learn-caching.md) costs nothing to repeat, so starting from someone else's result re-runs only the calls the cache does not hold.

## From the Client

The [Client](sf-client.md) reads and writes the board directly. To browse it:

```python
import screamingface as sf

sf.leaderboards.list()                      # 91 benchmarks on production

board = sf.leaderboards.get("draco-3pass", top=10)
for entry in board.entries:
    print(entry.rank, entry.score, entry.verified_by_screamingface)

board.baselines                             # single-model numbers, for comparison
```

To publish a result you ran yourself:

```python
score = sf.leaderboards.submit(report.candidates.only)
score.id                                    # the stable id of this submission
sf.leaderboards.get_score(score.id)         # read it back later
```

`submit()` takes a candidate out of a [Report](sf-client-api-reports.md), so you can only publish something you actually evaluated. To start from an existing entry instead, read its url4 back as code, or hand it straight to the engine:

```python
entry = board.entries[0]

entry.url4.to_python()   # the winning recipe as editable code, no spend
sf.evaluate(entry.url4)  # a new paid run over every case of the benchmark
```

## Known limits

Evaluation is nondeterministic. The same recipe run twice will not return the same number to the decimal, so ranks that sit close together are best read as tied rather than ordered. Treat a single run as one sample, not a settled result.

> The board is not a vote and not a vendor chart. Rankings come from graded benchmark runs behind the [engine](learn-engine.md)'s trust boundary, where the grading stays, and no rank can be bought or self-reported.

## Where the code lives

The board is [`apps/scoreboard`](https://github.com/ScreamingFace/screamingface/tree/main/apps/scoreboard): the submission and ranking API, the baseline registry, and the public portal. Submissions arrive at `POST /v1/scores`; the portal reads `GET /v1/leaderboard/{benchmark_id}`, with per-spec history under `/history`.
