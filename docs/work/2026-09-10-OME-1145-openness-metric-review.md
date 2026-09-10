---
ticket: OME-1145
stack: scoreboard
status: blocked
started: 2026-09-10
finished:
---

# OME-1145 — pre-work review of the "open frontier share" metric

## Intent

No code changes. This is the audit record for a twelve-round review of OME-1145 and the
epic filed against it (OME-1179 / OME-1180 / OME-1181), plus the owner decisions taken on
2026-09-10. It exists because four of the claims already written into those tickets are
wrong, and the corrections have not yet been applied to Linear. Read this before editing
any of the five tickets.

Nothing has been written to Linear. The pending edits are listed at the bottom.

---

## 1. What the board actually shows

Fetched anonymously from `https://leaderboard.dev.screamingface.ai/v1/...` on 2026-09-10.

| board | entries | baselines | on Pareto frontier | rows in the statistic | open_share |
| -- | -- | -- | -- | -- | -- |
| `draco-3pass` | 7 | 0 | **1** | **10** | 0.0 |
| `draco` | 0 | 0 | 0 | 0 | — |
| `gdpval-text` | 0 | 0 | 0 | 0 | — |
| `ifeval` | 0 | 0 | 0 | 0 | — |
| `medxpert` | 0 | 0 | 0 | 0 | — |
| `healthbench-professional` | 0 | 0 | 0 | 0 | — |

`draco-3pass` is the only populated board. All seven entries store
`ran_with_providers = ['openrouter']`. Every `run_cost_usd` is `0.000000`. The board is
pinned (`revision = 2634cec91fd0f19a`, `case_count = 100`).

The 10-vs-7 gap is the two code paths: the statistic counts every Score row, the table
counts best-per-spec.

### The models actually behind those rows

Recovered from each entry's stored `url4_expression`, splitting the `candidate:` binding
from the rest of the harness:

| spec | candidate models | harness |
| -- | -- | -- |
| `fable_plus_gpt` | claude-fable-5, claude-opus-4.8, gpt-5.5 | gemini-3.1-pro-preview |
| `opus_plus_gpt` | claude-opus-4.8, gpt-5.5 | gemini-3.1-pro-preview |
| `pareto_cross` | deepseek-v4-pro, kimi-k2.6, gpt-5.5 | gemini-3.1-pro-preview |
| `budget_trio` | claude-opus-4.8, deepseek-v4-pro, gemini-3-flash-preview, kimi-k2.6 | gemini-3.1-pro-preview |
| `best_open_source` | deepseek-v4-pro, kimi-k2.6, qwen3.6-plus | gemini-3.1-pro-preview |
| `pareto_lean` | deepseek-v4-pro, kimi-k2.6 | gemini-3.1-pro-preview |
| `claude-fable-5` | claude-fable-5 | gemini-3.1-pro-preview |

All routes are `openrouter/`-prefixed. `gemini-3.1-pro-preview` appears three times per
expression in every entry and is never a candidate model — it is the DRACO grader.

---

## 2. Two separate code paths, not one

The single most consequential finding. The openness percentage and the Pareto row marks
share a word and nothing else.

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

Each function has exactly one production caller. There is no shared code.

Consequences:

- The statistic **mixes benchmark revisions**. `_comparable` (`frontier.py:51`) applies only
  the OME-1056 case-count rule. Nothing filters on revision. Not currently visible because
  every live board has one revision.
- Implementing Irina's metric is a route migration, not a change to `_current_split`.
- Adding the `pinned` gate or a revision filter to the statistic changes what a live public
  endpoint returns for an unpinned board. Moot today — all seven boards are pinned.

---

## 3. `_current_split` is not a defect

`docs/spec/2026-07-16-open-vs-closed-frontier-stats-spec.md` resolved this on 2026-08-06:

> **Baseline timing, resolved (2026-08-06):** … Baselines still count toward the *current*
> open/closed split (§5), but are **excluded from the time-series trend**.

and pinned it as an acceptance criterion in §8:

> Baselines are included in the current open/closed split but excluded from the
> time-series trend (§6).

§6 also defines "the frontier" as *the single best score across all specs within a
benchmark* — score only. Cost arrived later, via OME-770 and OME-923. So the repo now has
two different concepts sharing the word "frontier", and `frontier.py`'s self-contradicting
docstring traces straight back to the spec, not to a coding error.

**OME-1145 is therefore a request to supersede an owner-resolved decision and its
acceptance criterion, not a bug report against the implementation.** Irina's own framing —
"Needs: A decision on the correct definition" — was right.

### Rule-5 cost

`apps/scoreboard/tests/unit/scores/test_frontier.py:92`,
`test_baseline_counts_in_split_but_never_becomes_trend_holder`, asserts
`open_count == 1`, `closed_count == 1`, `open_share == 0.5` with a Baseline in the
denominator. Its entire purpose is to pin that baselines count. Changing the metric changes
that test, which is a Confidence-Gate decision requiring owner approval.

`test_openness_override_changes_the_holders_reported_openness` (line 163) may also move.

---

## 4. Why the number is 0%

`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:502`:

```python
def _providers(models: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(model.split("/", 1)[0] for model in models))
```

Called at line 443. `openrouter/meta-llama/Llama-3.1-70B-Instruct` is submitted as
`"openrouter"`. `classify_score` reads `ran_with_providers`, matches `openrouter` on
`_CLOSED_PROVIDER_MARKERS`, and files an open-weights run as closed.

OpenRouter is the only provider that reports a cost — `DirectCost.reported(...)` has exactly
one caller, `apps/aigateway/src/aigateway/plugins/openrouter_provider/usage_accounting.py:115` —
so it dominates any board with cost data.

Live effect: an entry named `best_open_source`, running deepseek + kimi + qwen, is counted
closed.

---

## 5. The identities are already stored, and already public

Verified against the live payload, not a synthetic object. A real submitted
`url4_expression` is 21,105 characters and begins:

```
(candidate:0.0:'(model_1:0.0:/openrouter/anthropic/claude-fable-5?max_tokens=32768&q=($input)!'…
```

Every model route is literal. `url4_expression` is returned on the public
`LeaderboardEntry` payload (confirmed in the live entry keys), so the model identities are
already published on the board today.

**This resolves D6.** Sending a `models` field publishes nothing that is not already public.

### Why parsing `url4_expression` is still not the answer

Two reasons, both verified:

1. **The expression mixes the system under test with the harness grading it.** The DRACO
   grader `openrouter/google/gemini-3.1-pro-preview` appears three times in every
   expression, outside the `candidate:` binding. A naive extraction counts the judge as
   part of the candidate. Separating them means locating the candidate binding boundary and
   depending on the harness expression shape staying stable.
2. **The Scoreboard has no URL4 parser.** No `url4` entry in `apps/scoreboard/pyproject.toml`
   and no import anywhere in `src/`. Option C means adding `packages/url4` as a runtime
   dependency of the scoreboard image.

`CandidateResult.models` has neither problem: it is exactly the candidate's declared routes.
That is the real justification for OME-1180, and it is stronger than the one currently in
the ticket.

For the record, every model in every recipe kind reaches the expression through one of two
call sites — `_model_route(route)` at `_evaluation/candidate.py:215` (every `Model` node)
and `_model_route(synthesizer)` at line 267 — so route recovery *would* be complete if the
grader problem did not exist.

---

## 6. The keyword list does not hold the right answers

After stripping the routing prefix, `classify_providers` on realistic routes:

| route | weights | classifier | |
| -- | -- | -- | -- |
| `meta-llama/Llama-3.1-70B-Instruct` | open | open | ok |
| `qwen/Qwen2.5-72B-Instruct` | open | open | ok |
| `deepseek/deepseek-v3` | open | open | ok |
| `mistralai/Mistral-7B-Instruct-v0.3` | open | open | ok |
| `openai/gpt-5.5` | closed | closed | ok |
| `anthropic/claude-opus-4.8` | closed | closed | ok |
| `google/gemini-3-pro` | closed | closed | ok |
| `google/gemma-2-27b-it` | open | **closed** | **wrong** |
| `openai/gpt-oss-120b` | open | **closed** | **wrong** |
| `mistralai/mistral-large-2411` | closed | **open** | **wrong** |

Three of ten. Two of the three understate the open share — the exact complaint on OME-1145.
The cause is structural: `_OPEN_PROVIDER_MARKERS` and `_CLOSED_PROVIDER_MARKERS` conflate
model *owner* with openness, and Google, OpenAI and Mistral all now ship both.

On live data, `moonshotai/kimi-k2.6` matches nothing in either list and fails closed. So
`best_open_source` would read 2/3 open after the epic's fix, not 3/3.

> The open/closed judgements in the table above are my assessment of the models, not
> anything the repository asserts.

---

## 7. What the metric would actually read

Applying the epic's fix (candidate models, prefix stripped, current marker list) to live
`draco-3pass` data:

| definition | entries | models counted | open | share |
| -- | -- | -- | -- | -- |
| all 7 leaderboard entries | 7 | 18 | 5 | **28%** |
| Pareto frontier (today) | **1** | 3 | 0 | **0%** |

With every cost at `0.000000` the frontier degenerates to a single entry — `fable_plus_gpt`,
whose three models are all closed. **Irina's metric, correctly implemented, still reads 0%
on the only board with data.** OME-1143 is a hard blocker, not a nicety.

---

## 8. The manual override cannot be set

`openness_override` exists on both `Score` and `Baseline` and wins outright in
`classify_score` / `classify_baseline`. It has no write path anywhere in the application:
absent from `ScoreSubmission` and `BaselineImportRow` (both `extra="forbid"`),
`_submission_to_kwargs` lists every kwarg explicitly, and no route, CLI or script sets it.

`docs/work/2026-08-06-OME-323-implement-frontier-stats.md:70` records this as intended —
"The override is genuinely operator-only, as designed" — meaning a direct database edit.

Not verifiable from outside: whether any row currently has one set. The field is on
`ScoreSchema` but not on the public `LeaderboardEntry` payload.

Consequence: with the keyword list retained as the classification mechanism and no usable
override, correcting a misclassified model requires a code release.

---

## 9. Prior art that was missed

**OME-772** ("Feedback on leaderboard-mvp design gaps", filed 2026-08-11, assigned Irina,
status Pick Immediately) already catalogues this gap, and describes it more accurately than
the epic filed yesterday:

> | Models | partial | Only provider names + the opaque `url4_expression`, no clean list |

and:

> Models needs small work, not new architecture.

`apps/scoreboard/portal/benchmark.js:30` carries the same observation in a code comment:
"`ran_with_providers` is provider names, not model identities … Keeping the honest label
until a backend field exists."

One row of OME-772's gap table is now stale: the benchmark DTO does expose `focus`.

### Checked and not duplicates

- **OME-665** "Display models as provider/model handles" — Canceled the same day it was
  filed, legacy desktop UI.
- **OME-701** "Define provider grouping and classification in the API" — Studio presentation
  metadata, not open/closed weights. Does not supply an openness signal.
- **OME-428 / OME-394** — both Done. The OME-323 spec §4 required a cross-reference note on
  each pointing at the scoreboard's registry, so gateway-side classification would not
  silently diverge. **That note was never added.** Successor is OME-831 (Backlog, Dmitry).

---

## 10. Corrections to claims already written into Linear

| # | Where | Claim | Reality |
| -- | -- | -- | -- |
| 1 | OME-1179 c2, OME-1181 | "The frontier is gated by `pinned`, so the statistic reports `n/a`" | That gate is on the ranked leaderboard route. The statistic's route has no gate and no revision filter. Inheriting it means adding it, changing a live endpoint. |
| 2 | OME-1179 Problem | "`url4_expression` holds the compiled dataflow with `$candidate` placeholders" | It holds every model route literally, plus the harness grader's routes. |
| 3 | OME-1179 Problem | "The Scoreboard cannot tell which model produced a result" | It can, ambiguously — and the field is already public. |
| 4 | OME-1179, OME-1181 | "No new classifier is needed — it already holds the right answers" | Misses gemma and gpt-oss (open marked closed), mistral-large (closed marked open), and kimi (unknown → closed). |
| 5 | OME-1179, OME-1180 | `leaderboards.py:430` | `_providers` is at line 502; the call site is 443. |
| 6 | OME-1179 Not-in-scope | "`_current_split` … is a separate defect" | It is the specified behaviour, resolved 2026-08-06 and pinned by an acceptance criterion. |

Two further corrections to statements made in conversation, not written to Linear: "OME-775
exists to prevent revision mixing" was overstated (OME-775 is a catalogue-registration
ticket whose acceptance concerns *ranking*), and `benchmark.js:279` hides the card only when
there are zero rows, not at 0%.

**Process note.** Rounds 1–8 kept producing new contradictions because they reasoned from
synthetically compiled objects. Round 11 pulled the live payload and the picture settled in
one pass — including reversing two conclusions from rounds 6 and 7. Verify against the
deployed payload before asserting anything about what the board stores.

---

## 11. Decisions taken 2026-09-10 (owner)

| # | Decision |
| -- | -- |
| D-A | OME-1179 stays the implementation epic. Add a `relatedTo` link to OME-772; do not reparent. |
| D-B | Correct the `pinned` premise in both tickets, naming the two routes, and record separately that the statistic applies no revision filter. |
| D-C | Rewrite OME-1179's Problem section, and record "parse `url4_expression`" as a rejected option with its two reasons. |
| D-D | Keep the substring keyword list. Widen it inside OME-1181: add `moonshotai`/`kimi`, carve `gemma` and `gpt-oss` out of the owner-level closed markers, tighten `mistral`. Keep fail-closed logging. |
| D-E | Rewrite OME-1145's body; move Triage → Blocked. |
| D-F | Leave the live "0% open" card as it is — dev board, team audience. Record the exposure on OME-1145. |
| D-G | Record the baseline consequence in **both** OME-1145 (as part of the definition call) and OME-1179 (as a pointer for the implementer). |
| D-H | **Drop D5 entirely** from OME-1179. The override cannot be set, so there is nothing to decide. This removes the epic's only stated owner blocker, so OME-1181 is no longer gated on a decision. |
| D-I | Do not comment on OME-831. Record in OME-1179 that the scoreboard keeps its own list and that gateway-side classification would need reconciling. |
| D-J | Apply none of this to Linear yet. Write it here first. |

---

## 12. Pending Linear edits (not applied)

**OME-1179** — rewrite Problem (§5 above); add the rejected-option note; fix `:430` →
`:502`/`:443`; correct constraint 2 per D-B; correct the classifier claim per §6; drop D5;
record D6 as resolved; fix the "separate defect" wording; add the baseline pointer; add the
gateway-divergence note; add the live numbers from §7; add `relatedTo` OME-772.

**OME-1180** — fix the `:430` citation; replace the justification with the grader-ambiguity
argument from §5.

**OME-1181** — same constraint-2 correction; bring marker widening into scope per D-D;
remove the "Blocked on D5" section; add the baseline pointer.

**OME-1145** — rewrite the body per §3, §2, §7 and the rule-5 cost; note the live card
exposure; Triage → Blocked. The three `blockedBy` relations (OME-1179, OME-1143, OME-1156)
are already correct.

**OME-772** — picks up the relation from the OME-1179 side. No comment, no status change.

---

## Outcome

- **Actual files:** this ledger only. No source changes.
- **Commits:** see branch `OME-1145-openness-review`.
- **Gates:** not run — documentation-only change, no stack touched.
- **Deviations:** this ledger records pre-work analysis rather than an implemented unit, so
  the Planned changes / Test plan / Acceptance sections of `TEMPLATE.md` do not apply. The
  unit it describes is blocked and has not started.
