---
title: Accept and store model identities, and classify openness per model — spec
ticket: OME-1181
status: approved — Q2 and Q3 decided 2026-09-11, both CORRECTED after review of PR #922
date: 2026-09-11
parent: OME-1179
related:
  - https://linear.app/openmined/issue/OME-1181
  - docs/work/2026-09-10-OME-1145-openness-metric-review.md
---

# OME-1181 — Accept and store model identities

## 1. Problem

`packages/screamingface/.../leaderboards.py:502` reduces each declared model route to its
first path segment before submission, so `openrouter/deepseek/deepseek-v4-pro` arrives as
`"openrouter"`. Every live `draco-3pass` entry stores `ran_with_providers = ["openrouter"]`,
which `_CLOSED_PROVIDER_MARKERS` matches, so an entry whose declared models are deepseek,
kimi and qwen is published as closed.

This unit gives the Scoreboard the inputs to classify correctly. It publishes no new number.

## 2. Scope

| | here | elsewhere |
| -- | -- | -- |
| accept, bound and store `models` | ✅ | |
| derive `ran_with_providers` from it | ✅ | |
| `classify_model()` + registry fixes | ✅ | |
| bounded read of `models` for frontier ids | ✅ | |
| the Client sending `models` | | `OME-1180` |
| the metric and `/frontier` response | | `OME-1145` |

### 2.1 Wire and storage

`ScoreSubmission` gains:

```python
models: Annotated[list[ModelRoute], Field(min_length=1)] | None = None
```

`None` means the client did not send them. It is **not** the same as an empty list, which is
rejected — a submission that declares no models at all is a client bug, not a legitimate
state, and `CandidateResult.models` is a required non-empty field on the Client side.

`ModelRoute` mirrors `AuthorEmail`: an annotated `str` with a length cap and a pattern. The
pattern is the Client's own route grammar (`_MODEL_ROUTE_RE` in
`_evaluation/candidate.py:429`), so the two ends cannot disagree about what a route is.

`Score` gains a nullable `models` JSONField, and migration `0013_score_models` adds it —
the same shape as `0012_score_authors`, nullable and not backfilled.

### 2.2 Bounds

Three, mirroring the `authors` precedent (`_AUTHORS_MAX_DISTINCT`, `_AUTHORS_MAX_BYTES`):

| bound | proposed | why |
| -- | -- | -- |
| routes per submission | 32 | a fusion of 32 models is already implausible; the live maximum is 4 |
| length per route | 255 | matches `AuthorEmail`'s cap and the `spec_id` column |
| serialized size | 4096 bytes | identical to `_AUTHORS_MAX_BYTES` and `_METADATA_MAX_BYTES` |

All three raise a field error, so an oversized payload is a 422 and never a 500.

### 2.3 Deriving providers

When `models` is present, `ran_with_providers` is computed server-side from it rather than
stored from the client's copy, so the two fields cannot contradict each other.

**INVARIANT: `_content_hash` keeps reading `submission.ran_with_providers`, the wire value,
not the derived one.** The hash is recipe identity (`OME-391`); recomputing it from a
server-derived value would change every existing recipe's hash and split the board's dedup
history. In the normal case the two are identical, because the Client derives its providers
from the same routes. They diverge only when a client sends inconsistent fields, and in that
case storage should be honest while identity stays stable.

This derivation does **not** establish which models ran. Both values originate with the
submitter (`OME-1179`, Note on trust).

### 2.4 Classification

`OME-1179` D1 keeps the existing any-closed-wins aggregation, so there is no new algorithm.
What changes is the input and one extra verdict:

```python
def classify_model(route: str) -> Literal["open", "closed", "unknown"]: ...
```

**Route normalisation.** Strip a leading routing prefix before matching, or every
OpenRouter-carried route matches `openrouter` on the closed list regardless of the model it
names. Verified: feeding the full route to today's `classify_providers` still returns closed.

**Precedence.** A specific model rule beats its owner rule. Three carve-outs, all in the same
direction, all verified wrong today:

| route | today | required |
| -- | -- | -- |
| `google/gemma-*` | closed, via `google` | open |
| `openai/gpt-oss-*` | closed, via `openai` | open |
| `moonshotai/kimi-*` | closed, unmatched | open |

`mistral` stays a bare substring. Under `OME-1179` Q1 — open means weights you can download
and run — Mistral Large 2411 is already correct. The earlier "tighten mistral" instruction is
withdrawn.

**`unknown` must not collapse into `closed`.** Both close an entry under D1, but D4 requires
the count of unrecognised models to be reportable, so they are distinct return values. The
existing fail-closed `logger.warning` stays.

`classify_score` and `classify_providers` are untouched. They keep serving the existing
row-level surfaces until `OME-1145` replaces them.

### 2.5 Reading models for a frontier

A projection of `id, models` scoped to a set of score ids, **chunked**. The frontier is not
small or bounded — every best-per-spec point can be non-dominated and spec ids are
client-controlled — so a single `WHERE id IN (…)` can exceed database parameter limits.

It reads `id, models` and nothing else. `ParetoEntry` is not widened: `leaderboard.py:270-275`
records that the whole-board read stays minimal so client-controlled recipes and display
metadata are never materialised en masse.

---

## 3. DECIDED — Q2: `models` stays internal

`ScoreSchema` is the internal read DTO; `LeaderboardEntry` is the public payload.

Model identities are **already public** — `url4_expression` carries every declared route
literally and is returned on `LeaderboardEntry` today. So this is not a disclosure question.
It is an API-surface question: a typed `models` array makes that data directly enumerable and
creates a new wire contract to support.

| option | consequence |
| -- | -- |
| **A — internal only** (recommended) | `models` on `ScoreSchema`, absent from `LeaderboardEntry`. Classification works; nothing new is promised publicly. The portal's Backends column keeps reading `ran_with_providers` and keeps its honest label. `OME-1145` or a portal ticket can widen it later, when there is a consumer. |
| B — public now | `models` on `LeaderboardEntry` too. Lets the portal render real model names, which is the visible fix people will ask for. But it commits to the field before the Client populates it, so every row returns `null` until `OME-1180` ships and people resubmit. |

**Decided 2026-09-11: option A — internal only.** `models` lands on `ScoreSchema` and is
absent from `LeaderboardEntry`. It keeps this unit's blast radius inside the Scoreboard, and a
public field whose value is `null` on every row is worse than no field. The portal's Backends
column is untouched and keeps its honest label. Widening the public payload is a later change,
made when there is a consumer and real data behind it.

## 4. DECIDED — Q3: a same-owner republish may fill in `models`

Every existing row will have `models = null`. Two sub-questions.

**4a. Does a replay enrich a null `models`?** `store.py:835-849` builds the dedup `updates`
dict from exactly `authors` and `metadata`, so a resubmission carrying `models` against an
existing row is silently discarded today.

| option | consequence |
| -- | -- |
| **A — enrich on same-owner replay** (recommended) | Add `models` to `updates` under the existing `same_candidate_owner` guard, reusing its anti-hijack check and visibility locking unchanged. Rows fill in naturally as people resubmit. |
| B — leave null | Simplest. A row submitted before `OME-1180` can never gain identities, so the board carries permanently unclassifiable rows. |

**Decided 2026-09-11: option A — enrich on same-owner replay.** `models` joins `authors` and
`metadata` in the `updates` allowlist, under the existing `same_candidate_owner` guard. That
guard already requires a matching benchmark, stored content hash and submitter, and the write
already takes the visibility lock — both are reused verbatim, so this adds a field to an
existing allowlist rather than a new write path.

INVARIANT: enrichment fills a field, it does not overwrite a correct one with a worse one. The
same anti-hijack rule that protects `authors` protects this.

**4b. Do we backfill the seven live rows?** **Out of scope for this unit** (owner, 2026-09-11).
Not in this unit either way, but the answer shapes
what `OME-1145` can show. `url4_expression` does contain the routes; the grader-ambiguity
problem that ruled out runtime parsing is manageable in a one-off operator script where the
output can be inspected before it is committed. Proposed: **out of scope here, note it on
`OME-1145`** so the "metric is empty at launch" risk is visible where it matters.

**Not negotiable either way:** `models` must **not** enter `_content_hash`. It is a richer
projection of data already in `url4_expression`, which is hashed. Adding it would split one
recipe's identity merely because a newer client sent more detail about the same recipe.

---

## 5. Acceptance

* an optional `models` is accepted, stored, and survives round-trip
* `models: []` is rejected with a field error
* a submission without `models` still succeeds and stores `null`
* when `models` is present, stored `ran_with_providers` is derived from it
* `_content_hash` is unchanged by the presence of `models` — a resubmission carrying it dedups
  to the same row
* each of the three bounds rejects with a field error, not a 500
* `classify_model()` returns `unknown` for an unrecognised route, distinguishably from
  `closed`, and still logs it
* `classify_model()` classifies `gemma`, `gpt-oss` and `kimi` open — each pinned separately, so
  removing one carve-out fails one test
* a route classifies identically with and without its routing prefix
* `classify_score` / `classify_providers` behaviour is unchanged — pinned, since the existing
  frontier surfaces still call them
* the frontier-scoped read is chunked, exercised above one chunk boundary
* the migration ships in this iteration (stack rule S1)
* full Scoreboard gates green

## 6. Not in scope

`_current_split()`, the `/frontier` response shape, the portal's Backends column, anything
touching cost, and the Client change (`OME-1180`).

## 7. Risks

**Rollout.** This must be **deployed**, not merely merged, before `OME-1180` is released.
Merging `OME-1180` starts a release-please train to PyPI, and a released Client sending an
unknown top-level field 422s against an un-upgraded Scoreboard.

**The registry stays hand-maintained.** Q1 chose downloadable-weights as the definition, which
is knowable per model but not derivable from any field the Gateway exposes — checked, there is
no licence or `open_weights` signal in its discovery code. D4's visible-miss count is the
mitigation, not a fix.


---

## 8. Corrections after review of PR #922 (2026-09-11)

Three findings, all confirmed empirically. Two invalidate answers recorded above.

### 8.1 §3 was wrong — `models` is not internal

`ScoreSchema` is itself the response model for `POST /scores` (`routes/scores.py:179`) and
`GET /scores/{id}` (`:287`). Checking only that the field stays off `LeaderboardEntry` was not
enough.

The consequence is worse than disclosure. `export_private_submissions.format_jsonl` dumps this
schema in python mode with `sort_keys=True`, and `purge_private_benchmark.export_sha256` hashes
those exact bytes to authorize a destructive purge against an operator-supplied digest. Adding
`"models": null` changed every export saved before the field existed, **with no underlying row
having changed**, so a previously certified export could no longer authorize its own purge.

`ranking_notice` carries `exclude_if` for exactly this reason, documented three lines above
where `models` was added. `models` now carries it too. Verified: a legacy row exports byte
identically to `origin/main` — sha256 `ac966efd…b8a3`, 582 bytes on both sides.

### 8.2 §2.4 was exploitable — substring matching on a client-controlled string

Routes are submitted by clients. Matching an open marker anywhere in the route let a submitter
choose a verdict by choosing a name. All of these returned **open**:

* `openrouter/openai/not-gemma-proprietary`
* `openrouter/anthropic/kimi-wrapper`
* `openrouter/google/not-qwen-api`
* `openrouter/openai/gpt-5.5-llama-killer`

Matching is now structural. The route parses as `owner/model`; the owner is matched exactly
against open and closed sets, and a family exception is prefix-matched on the model segment and
**scoped to its owner** — `google/gemma-*` is open, `openai/gemma-*` is not. A route with no
owner segment is `unknown` rather than guessed at.

Mutation testing had confirmed that `gpt-oss` beat `openai`. It never tested that a *crafted*
name beat it too, which is the difference between checking a feature works and checking it
cannot be abused.

### 8.3 §4a was too permissive — enrichment must fill, not replace

`_content_hash` excludes `models`, so two submissions differing only in their routes share one
identity. The replay update was unconditional, so a same-owner replay could swap what an entry
is made of — and thus flip its published openness — without changing its identity or its url4
expression.

The code comment justifying this claimed `models` is deterministic per `content_hash` because
the hash covers `url4_expression`. True of an honest client, irrelevant to a careless or hostile
one, since `url4_expression` is free text. It now writes only when the stored value is null,
which is what the Q3 decision said in the first place.

### 8.4 Bookkeeping

The acceptance criterion requiring the unrecognised-model count to be **exposed** contradicted
this unit's own scope boundary, which assigns response-shape changes to `OME-1145`. Moved there;
this unit only guarantees `unknown` is a distinct verdict so the count is computable.
