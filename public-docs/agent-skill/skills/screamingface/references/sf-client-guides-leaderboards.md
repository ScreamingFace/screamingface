# Leaderboards

Source: https://docs.screamingface.ai/sf-client/guides/leaderboards

Browse ranked results, publish a CandidateResult, and pull the url4 back out.

A **leaderboard** is one benchmark's public ranking on the ScreamingFace Leaderboard. The Client reads and writes it through `sf.leaderboards`. Discovery and reads are free. They hit the leaderboard, not a model, and they do not need a provider connection.

Each ranked row keeps the exact [`url4`](sf-client-guides-reproduce-and-share.md) that produced the score, so anyone can fork or re-run the recipe. The leaderboard also stores `verified_by_screamingface`, which is a property of the engine that ran the submission. It is separate from who submitted the row. A run on the hosted engine is verified. A submission from a run on any other engine stays unverified on the public leaderboard until the hosted engine also runs it.

The public portal is [leaderboard.screamingface.ai](https://leaderboard.screamingface.ai). The Client's default leaderboard is that public portal, `https://leaderboard.screamingface.ai`. `sf.leaderboards.submit()` publishes there, with the author emails you pass, unless you point `scoreboard_url` at your own instance first. Do that before your first submission when you run the local stack.

## What you can do with it

-   List the benchmarks registered as leaderboards.
-   Fetch one board's ranked entries and any imported single-model baselines.
-   Publish an evaluated `CandidateResult` as a new score.
-   Add author and paper metadata when you publish, and edit it later.
-   Look up one published score by id and reuse its `url4`.
-   Replay a published score from its pinned cache at no provider cost, and record that it held.

## Main APIs

| API | What it does |
| --- | --- |
| `sf.leaderboards.list()` | Lists every benchmark registered with the configured leaderboard as `LeaderboardInfo` values. |
| `sf.leaderboards.get(id, *, top=50)` | Fetches one `Leaderboard`: the board's identity, best-per-spec ranked `entries`, and imported `baselines`. `top` caps how many entries come back (the service clamps above 200). |
| `sf.leaderboards.submit(candidate_result, *, authors=None, paper_url=None, authors_metadata=None, paper_metadata=None)` | Publishes one evaluated `CandidateResult`. The Client derives benchmark id, spec id, url4, the benchmark-native score, providers, and the idempotency key from that result. An optional author list supplies the exact credit line. An optional `paper_url` links the paper; the metadata objects add details about the authors and the paper. A result from a `cases=` run raises `ValueError`, because a leaderboard takes full runs only. |
| `sf.leaderboards.get_score(score_id)` | Loads one public `LeaderboardScore` by UUID (or its string form). |
| `sf.leaderboards.edit(score_id, *, authors=..., paper_url=..., authors_metadata=..., paper_metadata=...)` | Changes the authors, paper link or metadata of a score you submitted. Returns the updated `LeaderboardScore`. Only the submitter can do this. |
| `sf.leaderboards.metadata_events(score_id)` | Reads the edit log of a score you submitted, newest first, as `ScoreMetadataEvent` values. Only the submitter can read it. |
| `sf.evaluate(pinned_cache=...) · sf.evaluate(score_id=...)` | Replays a published run and returns a `Report`. Its single `CandidateResult.reproduction` holds the verdict. Pass `record_reproduction=False` to skip recording an exact replay. |
| `LeaderboardEntry` · `LeaderboardScore` · `LeaderboardBaseline` · `ScoreMetadataEvent` | The public value types: a ranked row, a persisted submission, an imported single-model line to beat, and one row of a score's edit log. |

Ranking is best-per-spec: for each `spec_id` the leaderboard keeps the highest score, and breaks ties by newest `submitted_at`. The table is then ordered by score descending. Baselines are imported separately and sit beside community entries; they are not the same as a submitted score.

## How to

### 1 · See which boards exist

```python
import screamingface as sf

sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)
boards = sf.leaderboards.list()
len(boards), [b.id for b in boards][:6]
```

```
(91, ['air_bench', 'arc_agi_2', 'bbh', 'contracteval', 'draco', 'draco-3pass'])
```

These ids are leaderboard registrations. They can overlap the engine's [benchmark](sf-client-guides-benchmarks.md) catalog, but they are not the same list. A board has to be registered before you can publish to it. This read is against the public leaderboard, so the sample configures the hosted services first. A local scoreboard lists only the boards registered on it: `medxpert`.

### 2 · Read one board

```python
board = sf.leaderboards.get("draco-3pass", top=5)
board
```

```
Leaderboard('draco-3pass', entries=5, baselines=0)
```

```python
[(e.rank, e.score, e.verified_by_screamingface) for e in board.entries]
```

```
[(1, 0.6869, True), (2, 0.6526, True), (3, 0.642, True), (4, 0.6192, True), (5, 0.6092, True)]
```

Each entry carries `score`, `total_questions`, the providers used, who submitted it when that is known, its separate `authors` credit line, the `verified_by_screamingface` flag, and the `url4` expression. Public author values normally omit email domains; full addresses distinguish authors whose local parts collide. Notebook displays render the board as an interactive widget; the fields above are what each entry holds.

On this board every row is verified. Treat `verified_by_screamingface=True` as the trust signal, not the mere presence of a row.

### 3 · Point the Client at a leaderboard

With no configuration and no local stack running, leaderboard calls use the default hosted ScreamingFace Leaderboard. When `screamingface up` is running, the module-level functions connect to that stack. A non-default `engine_url` requires `scoreboard_url` in `sf.configure()`; without it the call raises `ValueError`. Local development points both the engine and the leaderboard at the stack `screamingface up` starts:

```python
sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
```

Local writes are open. On the public leaderboard, `list` and `get` are public. `get_score`, `submit`, `edit` and `metadata_events` need a Cloudflare Access login, and access is granted by the OpenMined team: reach out to them.

### 4 · Publish a result

`submit` takes the evaluated `CandidateResult` directly, so you never re-enter the score. Pass `report.candidates.only` for a single candidate, or iterate `report.candidates` to publish every candidate in the report.

Two optional arguments add credit and context:

-   **`authors=[...]`:** the exact, ordered credit line. One to ten email addresses, duplicates preserved, in the order you give. It never adds the authenticated submitter for you; omit it to use the leaderboard's default credit line. Authorship grants credit, not ownership or access to a private submission.
-   **`paper_url="https://…"`:** the paper that reports the result. An `http` or `https` link of at most 2,048 characters, with a host and no whitespace, control characters or user info. The Client checks the shape before any HTTP; the leaderboard does not verify that the link resolves or that the authors wrote the paper. No paper yet? Leave it out and add the link later with `edit`.

#### Author and paper metadata

Two more arguments attach structured detail:

-   **`authors_metadata`:** maps each credited author's full email address to a flat object. Known keys: `full_name` and `institution`.
-   **`paper_metadata`:** one flat object. Known keys: `title`, `url` and `citation`.

Those five key names are reserved in either object: they require text and follow the limits below, even when used outside their usual author or paper context. Any other key is stored and returned but not shown by the portal; its value may be text, a finite number or a boolean. Nested objects, lists and null values are not accepted.

Each `authors_metadata` key must match a credited author, ignoring case, and removing an author removes their metadata. The portal reads an author's metadata by the published identifier: normally the email's local part, with the full address kept when two authors share a local part. Keep the original full addresses when sending edits; public keys are not edit keys.

| Field | Limit |
| --- | --- |
| Paper object or one author's object | 20 keys; key names are 1 to 64 characters |
| `authors_metadata` | At most 10 authors |
| `full_name`, `institution` | 200 characters each |
| `title`, `citation` | 300 and 2,000 characters |
| `url` | 2,048 characters; the same rules as `paper_url` |
| Other text values | 500 characters each |
| Each top-level metadata field | 64 KiB as stored JSON, including escaped text |

The SDK checks object shapes; the board checks bounds, author matching and link rules. Keys and text must be valid Unicode with no NUL character. `paper_metadata.url` and `paper_url` are the same link; if you supply both, they must agree.

```python
# Use the hosted stack, and capture the run so others can replay it.
sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)
# candidate is the Model, Fusion or Pipeline you want to evaluate.
# Without limit=, this is a paid run over every case of the benchmark.
report = sf.evaluate(candidate, benchmark="ifeval", capture=True)

# publish one candidate
score = sf.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    authors_metadata={
        "alice@example.com": {"full_name": "Alice Smith", "institution": "University A"},
    },
    paper_metadata={
        "title": "Our ensemble",
        "url": "https://arxiv.org/abs/2601.00001",
        "citation": "Alice Smith and Bob Jones. Our ensemble.",
    },
)

# or publish every candidate in the report
[sf.leaderboards.submit(c) for c in report.candidates]
```

Capture is off by default. With `capture=True` the Engine stores every model and web-tool result of the run in a pinned cache, so others can replay it. A run without a capture has no `pinned_cache`. Read `capture_status` on the result before you publish: a partial or missing capture cannot be reproduced. [Reproducing a submission](learn-caching.md) explains why.

#### Publish from a local engine

A run on a local engine always has `capture_status == "partial"`, because its pinned cache never leaves the local gateway. A local scoreboard accepts the submission and marks it `verified_by_screamingface=True`, since the local engine ran it. A run with `limit=` is a partial submission: `submit` emits an `EvaluationWarning`, and the board does not rank it.

```python
sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
model = sf.Model("openrouter/deepseek/deepseek-v4-flash")
report = sf.evaluate(model, benchmark="medxpert", limit=2, capture=True)

result = report.candidates.only
score = sf.leaderboards.submit(result, authors=["alice@example.com"])
result.capture_status, score.verified_by_screamingface
```

```
('partial', True)
```

The Client posts `score`, `total_questions`, the compiled `url4_expression`, provider names, required `run_cost_usd`, optional authors, the optional paper link, and client metadata. When the run has them, it also posts the run's pinned cache id, its `capture_status` and its answer seed. They are what `sf.evaluate(score_id=...)` needs later. Direct submissions require a non-null run cost; a genuine fully cached run sends zero, while imported and historical rows may still display an unknown cost. The `Idempotency-Key` header is the candidate's `run_id`, so a retry of the same run reuses the original score instead of inserting a duplicate. A resubmission by the same submitter can correct its author list or its paper link. If another correction wins the same race, the Client reports a retryable conflict; retry the submission.

The score is benchmark-native: the Client submits `CandidateResult.score` exactly as the benchmark's own grading produced it (fractional for DRACO's weighted rubrics, negative for HealthBench worst-30), and never derives a replacement from case grades, normalizes, or bounds it. The only universal requirements are that a score exists and is a finite number; unscored or non-finite results are rejected before HTTP.

### 5 · Fetch a published score

Pass the id `submit` returned (or any public score id). This sample is a real score read back from a local leaderboard:

```python
score = sf.leaderboards.get_score(score.id)
score.score, score.authors, score.verified_by_screamingface
```

```
(0.0, ('alice',), True)
```

`verified_by_screamingface` depends on the engine that ran the submission. This sample is read back from a local scoreboard, where the local engine verified it. On the public leaderboard, a submission from a run on another engine stays `False` until the hosted engine also runs it. Read that field before you trust a number you did not produce yourself.

### 6 · Edit what you submitted

You can change the authors, paper link and metadata of a score after you publish it. Only the verified submitter can do this. Another caller gets a [`LeaderboardError`](sf-client-api-errors.md). Each argument you leave out stays as it is, and you must pass at least one.

```python
score = sf.leaderboards.edit(
    score.id,
    authors=["alice@example.com", "carol@example.org"],
    authors_metadata={
        "alice@example.com": {"full_name": "Alice Smith", "institution": "University A"},
        "carol@example.org": {"full_name": "Carol Jones"},
    },
    paper_metadata={"title": "Our ensemble", "url": "https://arxiv.org/abs/2601.00001"},
)
score.paper_url, score.metadata_updated_at

# remove the paper link; leave authors as they are
sf.leaderboards.edit(score.id, paper_url=None)

# clear the author metadata; leave the credit line unchanged
sf.leaderboards.edit(score.id, authors_metadata=None)
```

A local scoreboard has no identity header, so `edit` and `metadata_events` fail there with HTTP 401 (`Missing X-User-Email`).

A new `authors` list replaces the old one exactly. It follows the same rules as on `submit`. You cannot clear it. To go back to the default credit line, pass the submitter's own address. `paper_url=None` removes the paper link. An edit that changes nothing writes no log entry.

For either metadata field, omission preserves it, `None` clears it, and an object replaces it in full. `{}` is an empty replacement. This includes the paper link: replacing `paper_metadata` without a `url` clears `paper_url`. Include the existing URL if you only want to change the title. A submit or resubmit omits metadata set to `None`; use `edit` to clear it.

Every change goes into an edit log. A resubmission that changes these fields writes to it too. The log holds the old and new values, so it can hold author emails that you removed on purpose. For this reason it is not public: only the submitter and the board's operators can read it. The newest entry comes first.

```python
for event in sf.leaderboards.metadata_events(score.id):
    print(event.edited_at, event.source, event.old_paper_url, "->", event.new_paper_url)
```

### 7 · Remix a score

To change the recipe, remix it. `url4.to_python()` is local and free. Passing the same `url4` to [`sf.evaluate`](sf-client-guides-running-an-evaluation.md) is a new paid run. The expression is already linked to its benchmark, so do not pass `benchmark=` or `limit=` again. Model output can move; the recipe identity does not.

### 8 · Reproduce a published run

Replay requires an Engine and Gateway that support pinned caches and hold the original capture. The example selects the hosted production services explicitly; for another deployment, change both URLs to that deployment's services. A capture in one deployment is not automatically available in another. Replaying a published run needs the hosted engine and a Cloudflare Access account the OpenMined team grants.

Choose **Reproduce** under Copy on a captured public leaderboard row to copy a snippet using `sf.evaluate(pinned_cache="…")`. Replace the placeholder below with that row's pinned cache id. The Client reads the original recipe and answer seed from the board, then asks the Engine to use only the captured answers. A missing answer in the pinned cache fails its case.

Captured answers avoid changes in provider responses, including model retirement. Replay still needs the original benchmark revision and compatible execution behavior; a pinned cache does not guarantee replay across Engine upgrades. The Python attribute is `pinned_cache`; saved report JSON and the Scoreboard wire keep the key `frozen_copy_id`.

```python
import screamingface as sf

# Select the hosted services for a public production leaderboard submission.
sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)

# Use the pinned cache id from a complete, public leaderboard submission.
replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
result = replay.candidates.only
if result.reproduction is not None:
    print(result.reproduction.outcome, result.reproduction.reason)

# replay without recording it on the board
sf.evaluate(pinned_cache="<pinned-cache-id>", record_reproduction=False)
```

The return value is a `Report`. Read its single `CandidateResult.reproduction`, a `Reproduction` object or `None`. The string verdict is on `.outcome`:

| Result | Meaning |
| --- | --- |
| `reproduction.outcome == "exact"` | The score, case count and benchmark revision match; the case digest matches too when the submission has one. This checks internal consistency, not independent verification of the submitted answers. |
| `reproduction.outcome == "failed"` | `reason` says why. `missed_cases` names cases the pinned cache could not answer. `cases_differ` detects a digest mismatch but does not identify which case results differ. |
| `reproduction is None` | A partial replay or a capture without a public score has no verdict and is never recorded. |

Only exact full replays are recorded on the board. For a public score, a leaderboard login is requested only after the exact verdict, if recording needs one. The Engine may require its own authentication. Pass `record_reproduction=False` to skip recording. If recording fails, the verdict stays `exact`, `recorded` is `False`, and `record_error` explains why. The API exposes `reproduction_count` and `last_reproduced_at`; the portal does not display a reproduction count.

#### Recipe and seed checks

You usually need only the pinned cache id. If you also pass `url4=`, it must describe the same parsed recipe as the published run. If you pass `answer_seed=`, it must equal the original seed. Omission, or `None`, uses the stored seed; `0` is a real seed. A run captured without a seed replays without one. Conflicting values raise `ValueError` before a run starts.

A replay takes no positional candidate and no `benchmark=`. It never captures: omit `capture` or pass `False`. Explicit `capture=True` raises `TypeError: capture=True cannot be combined with a replay; a replay captures nothing`. A pinned cache id that no public score uses, with no `url4=`, raises `ValueError`. If both `score_id` and `pinned_cache` are supplied, they must identify the same capture.

#### Private scores

Use `score_id=` for a private score you submitted. The Client tries the public read first, then the authenticated read only on a 404. The private read may require a leaderboard login before replay. Passing a pinned cache id alone does not discover a private score. The same call also works for a public score.

```python
# A private score is readable only by its submitter; log in when prompted.
replay = sf.evaluate(score_id="<score-id>")
```

#### Inspect a subset

`limit=n` replays the first `n` cases of a published run for debugging. Use a positive integer strictly smaller than its published case count; omit it for the full run. This is never judged or recorded. If the current Engine cannot rebuild the published recipe and a compatible subset, the Client raises `PlanningError` with code `partial_replay_unavailable` before execution. An unsubmitted capture cannot use `limit`.

```python
# Inspect the first case of a published run that has more than one case.
partial = sf.evaluate(pinned_cache="<pinned-cache-id>", limit=1)
partial.candidates.only.reproduction  # None: no verdict, never recorded
```

#### Replay an unsubmitted capture

Without a public score, supply the original `url4` and the original `answer_seed` if it had one. Omit the seed or pass `None` when it did not. The replay has no published result to compare, so its `reproduction` is `None`. If every case misses, an `EvaluationWarning` asks you to check the recipe and seed. The Client never fills misses with live calls.

```python
# captured is the CandidateResult from your original, unsubmitted run.
# Use the same engine/gateway that holds its pinned cache.
replay = sf.evaluate(
    pinned_cache=captured.pinned_cache,
    url4=captured.url4,
    answer_seed=captured.answer_seed,
)
replay.candidates.only.reproduction  # None: no published score to compare
```

#### When replay cannot proceed

A partial or unknown published capture raises `sf.ReproductionError` with code `not_reproducible` before execution. Every submission from a local engine has a partial capture, so replaying it raises this error. An Engine that does not confirm replay mode raises the same exception with code `replay_unsupported`. Read `exc.reproduction` for the outcome and reason; there is no returned report. The [Errors reference](sf-client-api-errors.md) shows how to catch it, and the [Reproduction reference](sf-client-api-leaderboards.md) lists the verdict fields and reasons.

```python
sf.evaluate(score_id=score.id)
```

```
ReproductionError: Score <score-id> cannot be replayed: its capture is partial
```

#### Remix the recipe

`score.url4.to_python()` gives you an editable recipe locally, for free. `sf.evaluate(score.url4)` starts a fresh evaluation that may call providers and incur costs. The url4 already names the benchmark, so do not pass `benchmark=` or `limit=` again. To replay captured answers, use one of the keyword forms above.

```python
plan = score.url4.to_python()   # Model / Fanout / Synthesize / Pipeline, free
sf.evaluate(score.url4)        # a new paid run; omit benchmark= and limit=
```

## What "verified" means here

Anyone with write access can publish a score. The board stores the claim and the recipe. `verified_by_screamingface` is a property of the engine that ran the submission: a run on the hosted engine is verified, because that engine can validate it and replay it from its cache. A submission from a run on any other engine stays unverified on the public leaderboard until the hosted engine also runs it. Until that flag is true, treat the row as a submission, not a verified ranking.

## Links

-   [Public leaderboard portal](https://leaderboard.screamingface.ai)
-   [Companion notebook: `00_quickstart.ipynb`](https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb), which walks list → evaluate → optional publish → run again
-   [Reproduce & share (url4)](sf-client-guides-reproduce-and-share.md) for reading and rebuilding expressions
-   [Caching and compute](learn-caching.md) for how a pinned cache is made, why it can be partial, and why a replay can fail
