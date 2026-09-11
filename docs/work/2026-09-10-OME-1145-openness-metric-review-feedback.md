---
ticket: OME-1145
stack: scoreboard
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1145 — feedback on the openness-metric review

## Intent

Verify the claims and proposed Linear edits in
`docs/work/2026-09-10-OME-1145-openness-metric-review.md` against `origin/main`, the live
development Scoreboard API, and the current Linear issues. This is review evidence only: it
does not change source code or Linear.

## Verdict

The review found the right architectural problem: the existing openness statistic and the
cost/score Pareto marks are separate implementations, the SDK throws away structured model
identities before submission, and the current classifier cannot classify mixed-owner model
families correctly.

The pending Linear edits should **not** be applied exactly as written yet. Five material
issues remain:

1. revision mixing is already visible in live data, not merely a hypothetical unpinned-board
   concern;
2. the row-level operator override still needs an explicit compatibility decision;
3. “open” has no sufficiently precise licence/weights definition for the proposed exceptions;
4. the proposed second query is not bounded; and
5. the API and legacy-row migration behavior is unspecified.

## Evidence checked

- `origin/main` at `17048f5d`.
- Anonymous live reads on 2026-09-10:
  - `GET https://leaderboard.dev.screamingface.ai/v1/benchmarks`
  - `GET https://leaderboard.dev.screamingface.ai/v1/leaderboard/draco-3pass`
  - `GET https://leaderboard.dev.screamingface.ai/v1/leaderboard/draco-3pass/frontier`
  - public per-spec history routes for every visible `draco-3pass` spec.
- Current Linear descriptions, relations, and comments for `OME-1145`, `OME-1179`,
  `OME-1180`, `OME-1181`, `OME-772`, `OME-428`, `OME-394`, and `OME-831`.
- Official model sources for the disputed classification examples:
  - [Google Gemma 2 model card](https://ai.google.dev/gemma/docs/core/model_card_2)
  - [Google Gemma terms](https://ai.google.dev/gemma/terms)
  - [OpenAI gpt-oss documentation](https://developers.openai.com/api/docs/models/gpt-oss-120b)
  - [Mistral Large 2411 model card](https://huggingface.co/mistralai/Mistral-Large-Instruct-2411)
  - [Moonshot Kimi K2.6 model card](https://huggingface.co/moonshotai/Kimi-K2.6)

## Claims confirmed

The following parts of the review are supported by both code and live behavior:

- `draco-3pass` currently returns seven ranked entries, no baselines, and one marked Pareto
  entry. All seven visible entries report `ran_with_providers=["openrouter"]` and
  `run_cost_usd="0.000000"`.
- The separate frontier-stat endpoint reports `open_count=0`, `closed_count=10`, and
  `open_share=0.0`.
- The current ranked-board Pareto calculation uses `leaderboard_pareto_inputs()` and
  `compute_pareto_frontier_ids()`. It applies the registered revision, best-per-spec collapse,
  case-count rule, and the `pinned` gate.
- The openness endpoint instead uses `list_all_for_benchmark()` and `compute_frontier()`. It
  reads every Score row, has no revision filter, does not use cost, includes Baselines in the
  current split, and returns 404 for a private board.
- `_current_split()` implements the earlier `OME-323` specification faithfully. In particular,
  the old spec deliberately includes Baselines in the current split while excluding them from
  the trend. Replacing that meaning requires an explicit Confidence-Gate exception; it is not
  an accidental one-line bug.
- `_submission()` sends provider prefixes derived from `CandidateResult.models`; `_providers`
  is at line 502 and its call site is line 443 on this revision.
- A live `url4_expression` contains the declared candidate routes literally and also contains
  the DRACO grader route three times. The seven candidate-model lists in the review match the
  live expressions.
- Scoreboard has no URL4 parser dependency. Adding a structured `models` field is preferable to
  parsing a harness-dependent expression.
- `CandidateResult.models` is required, ordered, non-empty, unique, and derived from the
  compiled recipe. It represents **declared candidate models**, not models observed from usage
  events.
- `ScoreSubmission` uses `extra="forbid"`, so Scoreboard support must deploy before the SDK
  starts sending a new top-level field.
- `openness_override` has no HTTP, CLI, or import-DTO write path. It is intentionally
  operator-only and can currently be changed only outside the normal application write path.
- OpenRouter is the only production AIGateway adapter currently calling
  `DirectCost.reported(...)`.
- `OME-772` does already record that the board has provider names and an opaque expression but
  no clean model list. It remains assigned to Irina in Pick Immediately, and its `focus` claim
  is stale.

## Corrections required

### 1. The live statistic already mixes revisions

The review says revision mixing is “not currently visible because every live board has one
revision.” That confuses a benchmark's one **registered** revision with the revisions stored on
its Score rows.

The live `draco-3pass` history contains seven scores at the registered revision
`2634cec91fd0f19a` and three older scores at `b8c8afd8f9dddca0`:

- old `pareto_cross`;
- old `claude-fable-5`; and
- old-only `claude-opus-5`.

The ranked leaderboard filters those old rows. The openness endpoint includes them. Its trend
currently exposes the old `claude-opus-5` score as its first point. Therefore the 10-versus-7
gap is not described fully by “all rows versus best-per-spec”; on today's data it is also the
direct result of missing revision filtering.

This changes the framing of `OME-1145`: changing the denominator from entries to Pareto models
supersedes an earlier product decision, but mixing incomparable benchmark revisions is a real
integration defect introduced by later revision semantics.

### 2. Empty-board API values are `0.0`, not a dash

For example, `/v1/leaderboard/draco/frontier` currently returns `open_share: 0.0`,
`current: null`, and an empty trend. The portal may suppress the card when there are no rows,
but a table described as API evidence should record `0.0` or explicitly label the dash as
portal presentation.

### 3. Use “declared models,” never “models actually behind the rows”

The URL4 evidence recovers what the submitted recipe declares. It does not prove the exact
provider response selected at runtime, and it does not turn `url4_expression` into a structured
model field. Recommended wording:

> The Scoreboard stores enough public recipe text to recover candidate model routes with
> harness-aware parsing, but it has no structured, unambiguous candidate-model field.

That is more accurate than either “the Scoreboard cannot tell at all” or “the Scoreboard can
tell which model produced the result.”

### 4. Public URL4 data does not resolve the API-shape decision

It is true that the model names already appear in a public field. A separate `models` array
does not disclose a new category of data. It does, however, make that data directly enumerable
and creates a new supported wire contract.

`D6` should therefore not be marked resolved merely because URL4 is public. The implementation
must still choose whether `models` is:

- stored and used internally only; or
- returned as a first-class public `LeaderboardEntry` field.

The privacy concern is largely resolved; the API compatibility and product-display decision is
not.

### 5. “Open” needs a precise definition before adding exceptions

The classifier counterexamples are valuable, but the table's `weights` column overstates the
certainty of the judgements:

- Gemma 2 has downloadable weights under Google's Gemma terms, which contain use restrictions.
- `gpt-oss-120b` has downloadable weights under Apache 2.0 plus the gpt-oss usage policy.
- Kimi K2.6 publishes code and weights under a Modified MIT licence.
- Mistral Large 2411 publishes downloadable weights under the Mistral Research License, which
  permits research/non-commercial use. Calling it “closed weights” is factually inaccurate;
  calling it unsuitable for a permissively licensed open category may still be a valid product
  decision.

The contract must say whether `open` means:

1. weights are downloadable and locally runnable;
2. weights are available under a permissive commercial licence; or
3. the complete stack meets a stricter open-source/reproducibility standard.

The earlier `OME-323` policy was routing-based and does not settle this licence boundary. Until
that definition is explicit, “tighten Mistral” is not an implementation-ready instruction.

### 6. A per-model classifier function is still needed

The existing `classify_providers(Sequence[str])` returns one row-level `open|closed` verdict and
implements any-closed-wins. The new statistic counts individual models. Even if the same marker
data is retained, the code needs a separate API such as `classify_model(route)` and explicit
precedence for exceptions such as:

- `openrouter/openai/gpt-oss-*` before the `openai` closed-owner rule;
- `openrouter/google/gemma-*` before the `google` closed-owner rule; and
- specific open Mistral families rather than the substring `mistral`.

Calling this “no new classifier” hides a real semantic change. Reusing the registry is fine;
reusing the aggregate function unchanged is not.

### 7. Do not drop the override decision

The heading “the manual override cannot be set” is too strong. It has no supported application
write path, but the model column exists precisely for an operator database correction. Current
values cannot be checked anonymously, and future values remain possible.

Consequently `D-H` is not safe. Absence of a normal write endpoint does not define what an
existing row-level override means in a per-model metric.

Recommended resolution:

> `openness_override` remains effective for the legacy row-level classifier and historical
> score trend. It does not affect the new per-model Pareto share because a row-level value cannot
> identify which constituent models it overrides. Model classification exceptions belong in
> the model registry.

That is an explicit compatibility decision and removes the blocker without pretending the
field does not exist.

### 8. A Pareto frontier is not bounded

`OME-1179` and `OME-1181` say the second model query is safe because the frontier is “small and
bounded.” It is neither guaranteed. Every best-per-spec point can be non-dominated, and the
number of submitted spec IDs is client-controlled. A large `WHERE id IN (...)` can also exceed
database parameter limits.

The second projection is still the right shape, but it must be implemented as a compact,
chunked/streamed query over `id, models`, with explicit bounds on:

- number of model routes per submission;
- length of each route; and
- total serialized model-field size.

It must never fetch URL4 expressions or display metadata for the whole board.

### 9. The public API migration is missing

The current `/frontier` response combines:

- `open_count`, `closed_count`, and `open_share` from all rows; with
- `current` and `trend` from the running best **score**.

Changing the counts to models on the **cost/score Pareto frontier** while leaving the trend as a
row-level score history makes one response contain two unrelated definitions. It also changes
the meaning and unit of existing public fields.

Prefer either:

- a new `pareto_openness` object/endpoint with explicit model-count field names; or
- a versioned replacement of the old response.

Do not silently reuse `open_count` for “number of open models” while `current.openness` still
means “row-level classification of the running best score.”

### 10. Legacy and deduplicated rows need a policy

Adding a nullable `models` column leaves every existing Score row without structured identities.
The current dedup replay path updates `authors` and `metadata`, but not cost or any future
`models` field. Re-submitting the same result from the new SDK would therefore return the old
row and discard the new model identities unless the implementation changes that behavior.

Before implementation, decide among:

- leave legacy rows unknown and accept that the live metric initially has no classified
  frontier entries;
- allow a same-owner dedup replay to enrich a null `models` field, with the same anti-hijack and
  visibility locking used for author/metadata updates; or
- perform a controlled one-time backfill/purge and resubmission.

Models should not be added to `content_hash`: doing so would split one recipe/result identity
only because a newer client sent a richer projection of data already present in the recipe.

### 11. Qualify the OpenRouter cost claim

OpenRouter is the only production Gateway adapter currently emitting
`DirectCost.reported(...)`. It does not follow that every priced Score must use OpenRouter:
`ScoreSubmission` accepts a caller-provided cost, and future adapters can add reporting.

Recommended wording:

> OpenRouter is currently the only implemented Gateway path that emits provider-reported direct
> USD cost, so it dominates the SDK-generated priced rows available today.

### 12. `OME-831` is not a successor openness-classification issue

`OME-831` is about Hugging Face `hosted_shared` credentials. Its scope does not define model
openness or reconcile registries. It is a successor to the hosted-credentials portion of
`OME-394`, not to the missing gateway openness signal. The recommendation not to comment there
is sound, but the review should remove “Successor is OME-831” from the classification discussion.

### 13. Small internal inconsistencies

- The introduction says four Linear claims are wrong; its table lists six. Use “several” or
  state the final count.
- With all costs equal, the Pareto frontier does not always contain exactly one row. It contains
  every row tied for the highest score at that cost. The live board has one because
  `fable_plus_gpt` is the unique highest-scoring zero-cost entry.

## Assessment of the proposed owner decisions

| decision | assessment |
| -- | -- |
| D-A — keep the epic and relate `OME-772` | Good. The two-package delivery still requires the epic and two landing issues. |
| D-B — correct the `pinned` premise | Good, but also record that stale revisions are already included in the live statistic. |
| D-C — rewrite the problem and reject URL4 parsing | Good. Use “declared candidate routes” throughout. |
| D-D — retain and widen the marker list | Viable only after defining `open`; implement model-specific precedence and a per-model classifier. |
| D-E — rewrite `OME-1145` and move it to Blocked | Good. Describe both the product-definition change and the live revision-mixing defect. |
| D-F — leave the dev card until the real fix | Reasonable for a team-only dev board. |
| D-G — record the Baseline consequence | Good. Baselines have no comparable cost and therefore cannot join the cost/score Pareto set. |
| D-H — drop the override question | Reject. Replace it with the explicit legacy-only override rule proposed above. |
| D-I — do not comment on `OME-831` | Good. Also stop describing `OME-831` as the successor classification work. |
| D-J — hold Linear edits until review | Good. |

The file calls these “owner decisions,” but the current Linear threads do not record them. If
they came from a separate owner conversation, link or summarize that source before treating
them as durable product decisions. Otherwise label them “proposed decisions.”

## Recommended delivery sequence

1. **Correct the Linear design first.** Add the definition of `open`, the API shape, the
   override compatibility rule, model-field bounds, and legacy/dedup policy.
2. **Scoreboard ships first (`OME-1181`).** Accept and validate optional declared model routes;
   store them with a migration; add a per-model classifier; expose or internally aggregate them
   according to the chosen API shape; query the frontier projection safely.
3. **Deploy Scoreboard.** Confirm an old client still submits successfully.
4. **SDK ships second (`OME-1180`).** Send `CandidateResult.models` verbatim and retain
   `ran_with_providers` for the existing Backends surface.
5. **Repair `OME-1145`.** Use the same registered-revision filtering, case-count rule, pinned
   gate, and full-board Pareto membership as the row marks. Do not derive membership from the
   displayed page.
6. **Close only after cost semantics are real.** `OME-1143`/`OME-1156` still determine whether
   the resulting live Pareto set is economically meaningful.

## Recommended changes to the pending Linear edits

In addition to the corrections already listed in the original review:

- `OME-1179`: add the exact live stale-revision evidence; keep D5 as a resolved compatibility
  rule rather than deleting it; define `open`; leave D6 open until the public DTO shape is
  chosen; remove the bounded-frontier claim; add legacy-row behavior.
- `OME-1180`: keep the server-first rollout and full declared routes; state that its release is
  blocked until the deployed Scoreboard accepts the field.
- `OME-1181`: specify field bounds, route normalization and classifier precedence, chunked
  frontier-model reads, public response shape, and same-owner dedup enrichment or an explicit
  no-enrichment decision.
- `OME-1145`: distinguish the specified-but-superseded all-row/Baseline denominator from the
  genuine stale-revision integration defect. Preserve or version the legacy trend instead of
  quietly combining it with model-level Pareto counts.
- `OME-772`: add only the `relatedTo` relation and leave its separate design decisions alone.

## Outcome

- **Actual files:** this feedback document only.
- **Commits:** not committed in this review turn.
- **Gates:** not run; documentation-only review with no application source changes.
- **Deviations:** none.
