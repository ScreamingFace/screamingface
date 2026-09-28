---
ticket: OME-1145
stack: scoreboard
status: blocked
started: 2026-09-10
finished:
---

# OME-1145 — pre-work review of the "open frontier share" metric

## Intent

No source changes. This is the audit record for a review of OME-1145 and the epic filed
against it (OME-1179 / OME-1180 / OME-1181), plus the decisions taken with the Scoreboard
owner on 2026-09-10.

It exists because several claims already written into those tickets are wrong. Read this
before editing any of the five tickets.

**Companion document.** `2026-09-10-OME-1145-openness-metric-review-feedback.md` is an
independent verification of an earlier revision of this file. Its corrections are absorbed
here; read it for the underlying evidence and licence citations.

**Provenance of the decisions in §11.** They were taken in a working session with Filip
Boltuzic, the Scoreboard owner and the assignee of OME-1145, on 2026-09-10. They are not
yet recorded in Linear.

---

## 1. What the board actually shows

Fetched anonymously from `https://leaderboard.dev.screamingface.ai/v1/...` on 2026-09-10.
Code references are against `origin/main` at `17048f5d`.

| board | ranked entries | baselines | on Pareto frontier | rows in the statistic | `open_share` |
| -- | -- | -- | -- | -- | -- |
| `draco-3pass` | 7 | 0 | **1** | **10** | `0.0` |
| `draco` | 0 | 0 | 0 | 0 | `0.0` |
| `gdpval-text` | 0 | 0 | 0 | 0 | `0.0` |
| `ifeval` | 0 | 0 | 0 | 0 | `0.0` |
| `medxpert` | 0 | 0 | 0 | 0 | `0.0` |
| `healthbench-professional` | 0 | 0 | 0 | 0 | `0.0` |

An empty board returns `open_share: 0.0`, `current: null`, empty `trend` — **not** a null or
a dash. The portal suppresses the card at `total === 0`, so nothing renders; that suppression
is presentation, not an API value.

`draco-3pass` is the only populated board. All seven ranked entries report
`ran_with_providers = ["openrouter"]` and `run_cost_usd = "0.000000"`. The board is pinned
(`revision = 2634cec91fd0f19a`, `case_count = 100`).

### The 10-vs-7 gap has two causes, not one

| revision | rows | specs |
| -- | -- | -- |
| `2634cec91fd0f19a` (registered) | 7 | the seven on the ranked table |
| `b8c8afd8f9dddca0` (superseded) | **3** | `claude-fable-5`, `pareto_cross`, **`claude-opus-5`** |

Best-per-spec collapse explains part of it. **Missing revision filtering explains the rest.**
`claude-opus-5` exists only at the old revision, so it never appears on the ranked table — yet
it is in the statistic's denominator and it holds the **first published point of the trend**
(2026-08-24T20:01:07, score 0.6527).

### Declared candidate models behind those rows

Recovered from each entry's stored `url4_expression` by separating the `candidate:` binding
from the rest of the harness. These are the routes the submitted **recipe declares**. They are
not proof of which provider response was selected at runtime.

| spec | declared candidate routes | harness |
| -- | -- | -- |
| `fable_plus_gpt` | claude-fable-5, claude-opus-4.8, gpt-5.5 | gemini-3.1-pro-preview |
| `opus_plus_gpt` | claude-opus-4.8, gpt-5.5 | gemini-3.1-pro-preview |
| `pareto_cross` | deepseek-v4-pro, kimi-k2.6, gpt-5.5 | gemini-3.1-pro-preview |
| `budget_trio` | claude-opus-4.8, deepseek-v4-pro, gemini-3-flash-preview, kimi-k2.6 | gemini-3.1-pro-preview |
| `best_open_source` | deepseek-v4-pro, kimi-k2.6, qwen3.6-plus | gemini-3.1-pro-preview |
| `pareto_lean` | deepseek-v4-pro, kimi-k2.6 | gemini-3.1-pro-preview |
| `claude-fable-5` | claude-fable-5 | gemini-3.1-pro-preview |

All routes carry an `openrouter/` prefix. `gemini-3.1-pro-preview` appears three times per
expression in every entry and is never a candidate model — it is the DRACO grader.

---

## 2. Two separate code paths, not one

The openness percentage and the Pareto row marks share a word and nothing else.

| | openness statistic | Pareto row marks |
| -- | -- | -- |
| route | `GET /v1/leaderboard/{id}/frontier` (`routes/leaderboard.py:400`) | `GET /v1/leaderboard/{id}` (`routes/leaderboard.py:235`) |
| function | `compute_frontier` (`scores/frontier.py:72`) | `compute_pareto_frontier_ids` (`scores/pareto.py:79`) |
| query | `list_all_for_benchmark` — **every** Score row (`store.py:1217`) | `leaderboard_pareto_inputs` — best-per-spec (`store.py:1135`) |
| revision filter | **none** | `registered_revision` (`store.py:545`) |
| `pinned` gate | **none** | yes (`leaderboard.py:276`, D12) |
| cost | not used | the whole basis |
| baselines | included | **excluded** — the query reads Score only |
| private board | 404 | returns empty entries |

Each function has exactly one production caller. No shared code.

Consequences:

- **The statistic mixes benchmark revisions, live, today.** `_comparable` (`frontier.py:51`)
  applies only the OME-1056 case-count rule. Nothing filters on revision. See §1 for the
  three stale rows and the stale trend point. This is a real integration defect introduced
  when revision semantics arrived (OME-775), not a hypothetical about unpinned boards.
- Implementing Irina's metric is a route migration, not a change to `_current_split`.
- **The migration fixes the revision defect for free**, because the frontier path already
  filters. It is an argument for the move rather than separate work.

---

## 3. `_current_split` is not a defect

`docs/spec/2026-07-16-open-vs-closed-frontier-stats-spec.md` resolved this on 2026-08-06:

> **Baseline timing, resolved (2026-08-06):** … Baselines still count toward the *current*
> open/closed split (§5), but are **excluded from the time-series trend**.

and pinned it as an acceptance criterion in §8:

> Baselines are included in the current open/closed split but excluded from the
> time-series trend (§6).

§6 also defines "the frontier" as *the single best score across all specs within a
benchmark* — score only. Cost arrived later, via OME-770 and OME-923. The repo therefore has
two different concepts sharing the word "frontier", and `frontier.py`'s self-contradicting
docstring traces to the spec, not to a coding error.

**OME-1145 is a request to supersede an owner-resolved decision and its acceptance criterion,
not a bug report against the implementation.** Irina's own framing — "Needs: A decision on the
correct definition" — was right.

### Rule-5 cost

`apps/scoreboard/tests/unit/scores/test_frontier.py:92`,
`test_baseline_counts_in_split_but_never_becomes_trend_holder`, asserts `open_count == 1`,
`closed_count == 1`, `open_share == 0.5` with a Baseline in the denominator. Its purpose is to
pin that baselines count. Changing the metric changes that test — a Confidence-Gate decision
requiring owner approval. Granted, see D-N.

`test_openness_override_changes_the_holders_reported_openness` (line 163) also moves under D-L.

---

## 4. Why the number is 0%

`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:502`, called at 443:

```python
def _providers(models: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(model.split("/", 1)[0] for model in models))
```

`openrouter/meta-llama/Llama-3.1-70B-Instruct` is submitted as `"openrouter"`. `classify_score`
reads `ran_with_providers`, matches `openrouter` on `_CLOSED_PROVIDER_MARKERS`, and files an
open-weights run as closed.

Live effect: `best_open_source`, running deepseek + kimi + qwen, is counted closed.

### It was nobody's decision

The spec (2026-07-16) recorded what it expected the field to hold:

> `ran_with_providers: list[str]` (provider name strings, e.g. `["openai", "anthropic"]`)

On that assumption, provider is a sound proxy for openness. Then routing changed under it:

| date | event |
| -- | -- |
| 2026-07-16 | spec assumes the field holds `["openai", "anthropic"]` |
| 2026-08-07 | OpenRouter lands in the Gateway (OME-428) |
| 2026-08-09 | the truncation is written in `f757921c`, a 4,317-line feature commit, no ticket ref, no comment |
| 2026-08-17 | the openness classifier ships with `openrouter` on the closed list (#519) |
| 2026-08-19 | "run any OpenRouter model" (#633) — OpenRouter becomes the default path |

The field is named *providers*, so the SDK supplied a provider. The classifier trusted the
spec's example. Nobody connected the two.

### Cost reporting, stated precisely

OpenRouter is currently the only implemented Gateway path emitting provider-reported direct USD
cost — `DirectCost.reported(...)` has one caller,
`apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py:115`. It does not
follow that a priced Score must be an OpenRouter row: `ScoreSubmission` accepts a
caller-provided cost, and future adapters can report. OpenRouter dominates the SDK-generated
priced rows available today.

---

## 5. The identities are stored and public, but not structured

A real submitted `url4_expression` is 21,105 characters and begins:

```
(candidate:0.0:'(model_1:0.0:/openrouter/anthropic/claude-fable-5?max_tokens=32768&q=($input)!'…
```

Every declared route is literal, and `url4_expression` is returned on the public
`LeaderboardEntry` payload.

Accurate statement of the gap:

> The Scoreboard stores enough public recipe text to recover candidate model routes with
> harness-aware parsing, but it has no structured, unambiguous candidate-model field.

That is more accurate than either "the Scoreboard cannot tell" or "the Scoreboard can tell
which model produced the result".

### Why parsing `url4_expression` is rejected

1. **The expression mixes the system under test with the harness grading it.** The DRACO grader
   `openrouter/google/gemini-3.1-pro-preview` appears three times in every expression, outside
   the `candidate:` binding. Naive extraction counts the judge. Separating them requires
   locating the candidate binding boundary and depending on the harness expression shape.
2. **The Scoreboard has no URL4 parser.** No `url4` entry in `apps/scoreboard/pyproject.toml`,
   no import in `src/`. This would add `packages/url4` as a runtime dependency of the image.

`CandidateResult.models` has neither problem: required, ordered, unique, non-empty, and exactly
the candidate's **declared** routes. That is the justification for OME-1180, and it is stronger
than the one currently in the ticket.

For the record, every model in every recipe kind reaches the expression through
`_model_route()` at `_evaluation/candidate.py:215` (every `Model` node) or `:267` (a Fusion
synthesizer), so route recovery would be complete if the grader problem did not exist.

### D6 is only partly resolved

Public `url4_expression` settles the **disclosure** question: a `models` array exposes no new
category of data. It does not settle whether `models` becomes a first-class public
`LeaderboardEntry` field or stays internal to classification. That is an API-surface and
product-display commitment, and it remains **open** (Q2).

---

## 6. The classifier needs work, and "open" needs a definition

### The registry data is wrong in both directions

After stripping the routing prefix, `classify_providers` on realistic routes:

| route | licence reality | classifier | |
| -- | -- | -- | -- |
| `meta-llama/Llama-3.1-70B-Instruct` | open weights | open | ok |
| `qwen/Qwen2.5-72B-Instruct` | open weights | open | ok |
| `deepseek/deepseek-v3` | open weights | open | ok |
| `openai/gpt-5.5` | API only | closed | ok |
| `anthropic/claude-opus-4.8` | API only | closed | ok |
| `google/gemini-3-pro` | API only | closed | ok |
| `google/gemma-2-27b-it` | downloadable, Gemma terms with use restrictions | **closed** | **wrong** |
| `openai/gpt-oss-120b` | downloadable, Apache 2.0 + usage policy | **closed** | **wrong** |
| `mistralai/mistral-large-2411` | downloadable, Mistral Research License (non-commercial) | open | **arguable** |
| `moonshotai/kimi-k2.6` | downloadable, Modified MIT | **closed** (unmatched) | **wrong** |

Two of these understate the open share — the exact OME-1145 complaint. The cause is structural:
the marker lists conflate model **owner** with openness, and Google, OpenAI and Mistral all now
ship both kinds.

Correction to an earlier revision of this file: Mistral Large 2411 was described as "closed
weights". That is inaccurate — the weights are downloadable under the Mistral Research License.
Excluding it from a permissive-commercial open category may still be the right product call,
but that is a definition, not a fact about the weights.

### Q1 — what does "open" mean?

Not answerable from the code. The contract must choose one:

1. weights are downloadable and locally runnable;
2. weights are available under a permissive **commercial** licence;
3. the whole stack meets a stricter open-source / reproducibility standard.

OME-323's policy was routing-based and does not settle this. Until it is chosen, "tighten
mistral" is not an implementation-ready instruction. **Open question.**

### A new classifier function IS needed

`classify_providers(Sequence[str]) -> open|closed` returns one row-level verdict under
any-closed-wins. A per-model count needs a different shape:
`classify_model(route) -> open|closed|unknown`, plus explicit precedence so specific model
rules beat owner rules:

- `openrouter/openai/gpt-oss-*` before the `openai` closed-owner rule
- `openrouter/google/gemma-*` before the `google` closed-owner rule
- specific open Mistral families rather than the bare substring `mistral`

Reusing the registry **data** is fine. Reusing the aggregate **function** is not. "No new
classifier is needed" was wrong and hides a real semantic change.

---

## 7. What the metric would read

Applying declared candidate models with the current marker list to live `draco-3pass`:

| definition | entries | models counted | open | share |
| -- | -- | -- | -- | -- |
| all 7 ranked entries | 7 | 18 | 5 | **28%** |
| Pareto frontier (today) | **1** | 3 | 0 | **0%** |

With every cost at `0.000000`, cost drops out of the domination test and the frontier reduces
to the highest-scoring rows. `fable_plus_gpt` is the unique highest scorer here, so the frontier
is one row — with ties it would be all the tied rows, not necessarily one.

So the metric, correctly implemented, still reads 0% until OME-1143 lands. That is a
**sequencing** constraint, not a design problem (D-K).

---

## 8. The manual override

`openness_override` exists on `Score` and `Baseline` and wins outright in `classify_score` /
`classify_baseline`. It has **no supported application write path**: absent from
`ScoreSubmission` and `BaselineImportRow` (both `extra="forbid"`), `_submission_to_kwargs` lists
every kwarg explicitly, and no route, CLI or script sets it.
`docs/work/2026-08-06-OME-323-implement-frontier-stats.md:70` records this as intended —
"genuinely operator-only, as designed" — meaning a direct database correction.

It is operator-only, **not nonexistent**. Current values are not observable anonymously (the
field is on `ScoreSchema` but not on the public `LeaderboardEntry`), and future values remain
possible.

### What D-L does to it

The external review recommended keeping the override effective for the legacy row-level trend
and ignoring it for the new per-model statistic. That compromise assumes the legacy trend
survives. Under **D-L it does not** — the whole `/frontier` response moves to the frontier and
per-model basis, and the holder-based trend is replaced.

`classify_score` has exactly two callers, both in `frontier.py`: `_current_split` and
`_compute_trend`. D-L replaces both. The override therefore loses its only consumer, and the
question becomes whether the column is removed or left dormant. **Open question (Q4).**

---

## 9. Prior art

**OME-772** ("Feedback on leaderboard-mvp design gaps", filed 2026-08-11, assigned Irina, Pick
Immediately) already records this, more accurately than the epic filed on 2026-09-09:

> | Models | partial | Only provider names + the opaque `url4_expression`, no clean list |

and:

> Models needs small work, not new architecture.

`apps/scoreboard/portal/benchmark.js:30` carries the same observation as a code comment. Both
framed it as a **display** gap; neither connected it to the openness percentage, which the same
field feeds. One row of OME-772's gap table is stale — the benchmark DTO does expose `focus`.

### Checked and not duplicates

- **OME-665** "Display models as provider/model handles" — Canceled the day it was filed,
  legacy desktop UI.
- **OME-701** "Define provider grouping and classification in the API" — Studio presentation
  metadata, not weights openness.
- **OME-428 / OME-394** — both Done. OME-323 §4 required a cross-reference note on each pointing
  at the Scoreboard registry so Gateway-side classification would not diverge. **Never added.**
- **OME-831** is Hugging Face `hosted_shared` **credentials**. It succeeds the credentials half
  of OME-394. It is **not** a successor for Gateway openness classification — no such ticket
  exists.

---

## 10. Corrections to claims written into Linear

| # | Where | Claim | Reality |
| -- | -- | -- | -- |
| 1 | OME-1179 c2, OME-1181 | "gated by `pinned`, so the statistic reports `n/a`" | That gate is on the ranked route. The statistic has no gate and no revision filter, and is mixing revisions live. |
| 2 | OME-1179 Problem | "`url4_expression` holds … `$candidate` placeholders" | It holds every declared route literally, plus the harness grader's routes. |
| 3 | OME-1179 Problem | "The Scoreboard cannot tell which model produced a result" | It stores recoverable recipe text, already public. What it lacks is a structured field. |
| 4 | OME-1179, OME-1181 | "No new classifier is needed — it already holds the right answers" | Wrong on gemma, gpt-oss and kimi; arguable on mistral-large. A per-model function is also required. |
| 5 | OME-1179, OME-1180 | `leaderboards.py:430` | `_providers` is at 502; the call site is 443. |
| 6 | OME-1179 Not-in-scope | "`_current_split` … is a separate defect" | It is specified behaviour, resolved 2026-08-06 and pinned by an acceptance criterion. |
| 7 | OME-1179, OME-1181 | the frontier set is "small and bounded" | Neither is guaranteed. Every best-per-spec point can be non-dominated and spec ids are client-controlled. |
| 8 | OME-1179 c2 | `leaderboard.py:293` | `pinned` is at line 276 on `origin/main`. |

Corrections to earlier revisions of **this document**:

- "Not currently visible because every live board has one revision" — wrong. Three of ten rows
  on `draco-3pass` are at a superseded revision, and one is the first trend point.
- Empty boards were shown as "—". They return `0.0`.
- Mistral Large 2411 was called "closed weights". It has downloadable research-licensed weights.
- "A historical frontier needs cost data we didn't have then" — wrong. Rows are immutable and
  carry their own cost and timestamp, so the series is a straightforward replay. The real
  obstacle is that pre-OME-1143 costs are `0.000000` and unrecoverable.
- "The frontier degenerates to exactly one row at uniform cost" — it degenerates to every row
  tied for the top score. One here only because `fable_plus_gpt` is the unique top scorer.
- OME-831 was described as the successor classification ticket. It is credentials.
- The intro said four Linear claims were wrong. The count is eight.

**Process note.** Repeated rounds of self-review kept producing new contradictions while
reasoning from synthetically compiled objects. The picture settled once the live payload was
pulled — which also reversed two conclusions. Verify against the deployed payload before
asserting what the board stores.

---

## 11. Decisions taken 2026-09-10 with the Scoreboard owner

| # | Decision |
| -- | -- |
| D-A | OME-1179 stays the implementation epic. Add `relatedTo` OME-772; do not reparent. |
| D-B | Correct the `pinned` premise in both tickets, name the two routes, and record the live stale-revision evidence. |
| D-C | Rewrite OME-1179's Problem section; record "parse `url4_expression`" as a rejected option with its two reasons; use "declared candidate routes" throughout. |
| D-D | *(revised)* Keep the substring registry as the **data** source and widen it. A per-model `classify_model` function with model-before-owner precedence is still required. Blocked on Q1. |
| D-E | Rewrite OME-1145's body; Triage → Blocked. Describe both the product-definition change and the live revision-mixing defect. |
| D-F | Leave the live "0% open" card as it is — dev board, team audience. Record the exposure on OME-1145. |
| D-G | Record the Baseline consequence in **both** OME-1145 and OME-1179. |
| D-H | *(revised — was "drop D5")* Do not silently drop it. Record that under D-L the override loses its only consumer, and raise Q4. |
| D-I | Do not comment on OME-831. Record in OME-1179 that the Scoreboard keeps its own registry and that Gateway-side classification would need reconciling. Stop calling OME-831 a successor. |
| D-J | Hold all Linear edits until this document is reviewed. **Satisfied** — reviewed, then applied 2026-09-10; see §13. |
| D-K | Assume OME-1143 lands and costs become real. The one-row frontier is a **sequencing** fact — it blocks demonstrating the fix, not designing it. |
| D-L | **API shape: option (a).** Move the entire `/frontier` response to the frontier and per-model basis. The holder-based trend is **replaced** by an open-share-over-time series, not adapted. Justified because the board is in testing and nothing depends on the August history. |
| D-M | Leave the existing pre-OME-1143 rows in place. They will likely be deleted later. Trend points computed before real costs are meaningless and unrecoverable. |
| D-N | Accept the consequences of the move: a small and volatile numerator, baselines leaving the statistic, superseding the 2026-08-06 spec resolution, and the rule-5 change to `test_frontier.py:92`. Owner approval granted. |

### Open questions

| # | Question |
| -- | -- |
| Q1 | What does "open" mean — downloadable weights, permissive **commercial** licence, or a stricter reproducibility standard? Blocks D-D's registry work. |
| Q2 | Is `models` a first-class public `LeaderboardEntry` field, or internal to classification only? (D6, reopened.) |
| Q3 | Legacy and deduplicated rows: leave `models` null, allow same-owner dedup replay to enrich a null field, or do a controlled backfill? `models` must **not** enter `content_hash`. |
| Q4 | After D-L removes its only consumer, is the `openness_override` column removed or left dormant? |

---

## 12. Implementation constraints for OME-1181

Beyond the corrections, three things must be specified before code:

**Bounded model reads.** The second projection over frontier ids must be chunked or streamed
over `id, models` only, with explicit bounds on routes per submission, length per route, and
total serialized field size. A large `WHERE id IN (…)` can exceed database parameter limits. It
must never fetch URL4 expressions or display metadata for the whole board.

**Rollout order is one-directional.** `ScoreSubmission` is `extra="forbid"` (`schemas.py:302`),
so an older Scoreboard returns 422 for an unknown top-level field. Scoreboard (OME-1181) must
deploy before the SDK (OME-1180) is released.

**Dedup enrichment.** `store.py:835-849` builds the replay `updates` dict from exactly two
fields, `authors` and `metadata`. A resubmission carrying `models` against an existing row is
silently discarded today. Q3 decides whether that changes; if it does, it needs the same
anti-hijack and visibility locking the author/metadata path uses.

---

## 13. Linear edits — APPLIED 2026-09-10

All five tickets updated via MCP after this document was reviewed. No comments were posted
on anyone's ticket; OME-772 received only the relation.

One scope change was made during application, beyond the corrections listed here: the
boundary between OME-1181 and OME-1145 was redrawn. OME-1181 now provides the **inputs**
(accept, store, derive, `classify_model()`, bounded frontier read) and OME-1145 owns the
**metric and the public response**. The first version had OME-1181 doing the counting, which
would have made it undeployable ahead of the Client — the opposite of what the one-directional
rollout requires.

What each ticket received:

**OME-1179** — rewrite Problem per §5; add the rejected-option note; fix `:430` → `:502`/`:443`
and `:293` → `:276`; correct constraint 2 per D-B with the live stale-revision evidence; correct
the classifier claim per §6 and add the per-model function requirement; remove the "small and
bounded" claim and replace with the bounding requirements; replace D5 per D-H; reopen D6 as Q2;
add Q1, Q3, Q4; fix the "separate defect" wording; add the baseline pointer; add the
Gateway-divergence note; add the live numbers from §7; add `relatedTo` OME-772.

**OME-1180** — fix the `:430` citation; replace the justification with the grader-ambiguity
argument from §5; state that release is blocked until the deployed Scoreboard accepts the field.

**OME-1181** — same constraint corrections; per-model classifier with precedence; registry
widening blocked on Q1; field bounds and chunked frontier reads per §12; the D-L response shape;
the Q3 dedup decision; remove the "Blocked on D5" section.

**OME-1145** — rewrite per §3, §2, §7 and the rule-5 cost; separate the superseded all-rows
denominator from the genuine stale-revision defect; note the live card exposure; Triage →
Blocked. The three `blockedBy` relations (OME-1179, OME-1143, OME-1156) are already correct.

**OME-772** — picks up the relation from the OME-1179 side. No comment, no status change.

---

## Outcome

- **Actual files:** this ledger and its companion feedback document. No source changes.
- **Commits:** branch `OME-1145-openness-review`.
- **Gates:** not run — documentation only, no stack touched.
- **Deviations:** this ledger records pre-work analysis rather than an implemented unit, so
  `TEMPLATE.md`'s Planned changes / Test plan / Acceptance sections do not apply. The unit it
  describes is blocked and has not started.
