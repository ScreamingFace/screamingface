# Spec — a Benchmark may give each Case several Attempts, and a Check passes if any Attempt passes it

- Status: draft for owner review. Decisions D1–D14 approved by the owner on OME-1458,
  2026-10-07 (§1); D5 and D7 were revised after reading the code and re-approved the same day.
- Component: `apps/screamingface-engine` (the grading spine and `screamingface_engine_inspect`)
  and `packages/screamingface` (decoder and Report).
- Ticket: OME-1458. Parent epic: OME-1299. Unblocks OME-1476 (ARC-AGI-2).
- Ledger: `docs/work/2026-10-07-attempts-per-case-spec.md`.
- Delivery: this docs PR and an importer refusal close OME-1458; the build is a new ticket of
  three PRs (§7).

## TLDR

Some Benchmarks let the model hand in more than one answer per question and mark the question
right if **any** answer is right. ARC-AGI-2 gives two Attempts per test grid; ZeroBench and MBPP
publish the same rule as pass@k. Think of it as an exam that accepts two answer sheets.

The rule that must hold: **our score for such a Benchmark is the number its authors publish**, so
the Attempts are reproduced, never approximated, or the Benchmark is refused by name.

Today it breaks in two places:

- **The spine has room for one sheet.** Each Case calls the Candidate once and grades one answer,
  so a hand-built ARC-AGI-2 could only publish its first-Attempt score, which is lower than the
  published one.
- **The inspect importer ignores `epochs`.** A Task that declares several epochs is imported and
  run with one, silently. No published Benchmark is affected today (every imported Task declares
  one epoch), but the next import of MBPP or ZeroBench would be.

**The change: a Benchmark declares `attempts=N`; the Engine asks each Case N times, grades each
Attempt on its own, and marks a Check met if any Attempt met it.** The Report shows every
Attempt; the Leaderboard ranks the one Headline Score, as today. It never scores a declared
Attempts rule at one Attempt without saying so. Blast radius: nothing changes for a Benchmark
that declares no Attempts; its Case Results, Report and Benchmark Revision stay byte-identical.

## 1. The decisions, and the five questions the ticket asked

| # | Decision | Ticket question |
|---|---|---|
| D1 | **k independent Attempts per Case, any-match** (option b). Options a (k answers in one reply) and c (refuse forever) are rejected. | — |
| D2 | **Any-match is the only rule.** pass@1 estimated from N samples, all-must-match (ZeroBench's pass^k) and mean-over-Attempts wait until a Benchmark needs them. | Q3 |
| D3 | A new required-when-set field `attempts` on `BenchmarkDeclaration`, shown in the catalogue and pinned into the Benchmark Revision only when N > 1. | Q1 |
| D4 | The catalogue says **"any of N Attempts"**, never a bare "pass@N": inspect's `pass_at` means the unbiased estimator, a different number (§2.1). | Q1 |
| D5 | **Revised.** Attempt 1 is sent exactly as today. Attempt i ≥ 2 differs only in what keeps it from being a copy of Attempt 1: a seed derived from the run's answer seed when the run declared one, and a cache opt-out when it did not (§2.3). The owner first approved "one seed per Attempt"; that would refuse every Anthropic model (§2.3). | Q2 |
| D6 | One Attempt of a Fusion is one full fusion, members and synthesizer, as a solo Model gets one full call. | Q2 |
| D7 | **Revised.** The fold is per **Check**: a Check is met if any Attempt met it, and the Case score is the share of met Checks. For a Benchmark with one Check per Case this is "the best Attempt wins". The owner first approved "best Attempt per Case"; that undercounts ARC-AGI-2 (§2.4). | Q3, Q4 |
| D8 | Partial credit is per output: an ARC-AGI-2 task with two test grids, one matched, scores 0.5. That is what the ARC Prize's own scorer computes. | Q4 |
| D9 | The Report shows each Attempt's answer and grade, and which Attempts matched, only when N > 1. | Q3 |
| D10 | Question 5 (multiply the pre-run Cost Estimate by k) has nothing to multiply: no Cost Estimate exists in code (ADR 0003). The catalogue says "N Candidate Invocations per Case" instead, and the Report shows the cost actually spent. | Q5 |
| D11 | The importer maps inspect's any-match reducers to `attempts=N` and refuses every other reducer by name. | — |
| D12 | Until the build lands, the importer refuses every `epochs` > 1 by name (OME-1458, PR 2). | — |
| D13 | The build is proven by a test-only Benchmark declaring two Attempts; ARC-AGI-2 proves it for real in OME-1476. | — |
| D14 | OME-1458 closes when this spec and the refusal merge; the build is its own ticket. | — |

## 2. Design

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 440}}}%%
flowchart TB
  subgraph TODAY["TODAY — an Attempts Benchmark scores its first Attempt only, and nobody is told"]
    direction LR
    a1["inspect Task<br/>epochs = 2, any-match"] -->|importer reads the Task| a2["⚠️ importer<br/>never reads epochs"]
    a2 -->|one Candidate Invocation per Case| a3["⚠️ one answer, one grade<br/>score = first Attempt only"]
    a3 -->|published| a4["Leaderboard<br/>a number lower than the paper's"]
  end
  subgraph AFTER["AFTER — every Attempt is asked fresh, and a Check passes if any Attempt passed it"]
    direction LR
    b1["Benchmark declares<br/>attempts = 2"] -->|each Case asked twice| b2["Attempt 2 is never<br/>a copy of Attempt 1"]
    b2 -->|each Attempt graded on its own| b3[("Case Result<br/>both Attempts kept<br/>Check met if either met it")]
    b3 -->|Headline Score only| b4["Leaderboard<br/>the published any-of-2 number"]
  end
  subgraph KEY["HOW TO READ — colours"]
    direction LR
    k1["⚠️ where it breaks today"]
    k2["changed path"]
    k3[("record at rest")]
    k4["unchanged"]
  end
  TODAY ~~~ AFTER
  AFTER ~~~ KEY
  classDef bad   fill:#7f1d2b,stroke:#e5484d,color:#ffe8ea
  classDef good  fill:#14532d,stroke:#30a46c,color:#dcfce7
  classDef data  fill:#4c1d95,stroke:#a06ed4,color:#ede9fe
  classDef plain fill:#374151,stroke:#9ca3af,color:#f3f4f6
  class a2,a3,k1 bad
  class b1,b2,k2 good
  class b3,k3 data
  class a1,a4,b4,k4 plain
  style TODAY fill:#1f2937,stroke:#e5484d,color:#f3f4f6
  style AFTER fill:#1f2937,stroke:#30a46c,color:#f3f4f6
  style KEY fill:#111827,stroke:#6b7280,color:#f3f4f6
```

**The cost lands on the researcher who can't trust the number.** An ARC-AGI-2 score computed
from one Attempt sits below every published score and looks like a weak model, not a different
rule. After: the number matches the ARC Prize's own scorer, and the Report shows which Attempt
earned each point.

### 2.1 What the published rules say, and what inspect does

| Source | Rule | Evidence |
|---|---|---|
| ARC Prize harness | **Two Candidate Invocations per test grid**, same prompt each time; a grid passes if either reply matches exactly; a task scores matched grids ÷ grids | `arcprize/arc-agi-benchmarking@9e2828fb`, `main.py:261-291` (`--num_attempts` default 2), `scoring/scoring.py:122-127` |
| ARC-AGI-2 evaluation set | 120 tasks: 75 with one test grid, 43 with two, 2 with three (167 grids) | `arcprize/ARC-AGI-2@f3283f72`, `data/evaluation/*.json` |
| ZeroBench | pass@5: five samples at temperature 0.7, correct if any is correct | arXiv 2502.09696 |
| inspect `Epochs(N, reducer)` | each epoch is a full, separate run of the Sample; the same seed is sent on every epoch; the cache keys on the epoch | `inspect_ai` 0.3.263, `_eval/task/run.py:1752-1756`, `model/_cache.py:91-98` |
| inspect `pass_at(k)` | the unbiased estimator 1 − C(n−c, k) / C(n, k) over all n epochs. It equals any-match only when k = n | `scorer/_reducer/reducer.py:163-205` |
| inspect `max`, `at_least(1)` | any epoch correct → correct | same file, :129-160, :247-301 |

So inspect's `pass_at_5` with 5 epochs is our any-of-5; MBPP's `pass_at_1` with 5 epochs is an
average, a different number, and stays refused (D2).

### 2.2 The declaration: `attempts`, absent unless set

`BenchmarkDeclaration` gains `attempts: int`, the number of Attempts per Case. It is the
record's own named extension point for declared axes, and grading is untouched by declaring it.

- **One means "no Attempts rule".** At 1 the field is left out of `as_block()`, the catalogue
  and the Benchmark Revision, the `inverted_grade` precedent, so no published Revision, catalogue
  entry or rendered expression moves.
- **Above one, it is pinned.** Changing N changes what the score means, so it changes the
  Benchmark Revision; the catalogue shows "any of N Attempts · N Candidate Invocations per Case".
- **Hand-built Benchmarks** set it in their declaration. **Imported Benchmarks** get it from the
  importer (§2.6).

### 2.3 Running the Attempts: Attempt 2 must not be a copy of Attempt 1

The per-Case step runs the Candidate Invocation and its Grading once per Attempt, in order 1 to
N, inside the one Case. One Attempt is one complete answer: for a Fusion that is every member
and the synthesizer (D6), for a Corrective Loop every round.

**The trap is the AI gateway's cache, not the seed.** A model with no seed already answers
differently each time it is asked; the problem is that Attempt 2 is never asked. The gateway
keys a stored reply on the exact request, by design with no sampling member
(`GlobalChatCacheKey`, OME-305):

- Attempt 1 sends `gpt-x` "What is 6 times 7?"; the gateway calls the provider, gets `41`, and
  stores it under that exact request.
- Attempt 2 sends the identical request; the gateway finds the stored `41` and returns it
  without calling the provider.

Both Attempts say `41`, and the score is silently first-Attempt again. inspect avoids this by
putting the epoch number in its cache key; our cache is shared across every hosted user and
stays exact. So Attempt i ≥ 2 changes its request, and only in a way the Candidate does not see:

| The run declared | Attempt 1 | Attempt i ≥ 2 | Why |
|---|---|---|---|
| no seed (the normal case, and every Anthropic model) | today's request, unchanged | no seed, the cache opt-out `use-cache: false` | the provider is asked afresh and samples a new answer; a seed is not needed, and would refuse every Anthropic model (its Messages API has no `seed`) |
| an answer seed `s`, chosen by the researcher | today's request, seed `s` | seed derived from `(s, i)`, cached as normal | the run stamps `s` on every answer, and a provider that honours seeds returns the same answer for the same seed, so Attempt 2 needs its own; every Candidate Model already supports `seed` (the SDK refuses a seeded run otherwise), and a distinct seed is a distinct cache entry, so a rerun replays every Attempt |

Attempt 1 is byte-identical to today's request, so a Benchmark without Attempts never changes
its egress. The Benchmark's own Judges are untouched: a Judge grading the same answer twice may
be served the same stored verdict, which is right.

### 2.4 Grading and the fold: per Check, not per Case

Each Attempt is graded by the Benchmark's own Grading, unchanged, into its own Case Grade. The
per-Case envelope then folds the N grades into the Case's one Case Grade:

- **A Check is met if it is met in any Attempt.** The folded Check records which Attempts met
  it.
- **The Case score is the share of Checks met.** For every Imported Benchmark, which grades one
  Check per Case, this is the best Attempt's score.
- **The Case Result's shown answer** is the first Attempt with the highest Case score, so the
  answer a reader sees is one that earned the points.

Why per Check, not "pick the best answer sheet": one ARC-AGI-2 task can ask for two output
grids, A and B, one Check each (45 of the 120 evaluation tasks ask for two or three).

| | Grid A | Grid B |
|---|---|---|
| Attempt 1 | ✅ right | ❌ wrong |
| Attempt 2 | ❌ wrong | ✅ right |

- **ARC's own scorer** checks each grid on its own: A passed (Attempt 1), B passed (Attempt 2),
  so the task scores **1.0**.
- **Best Attempt per Case** treats each Attempt as one whole sheet: Attempt 1 scores 0.5,
  Attempt 2 scores 0.5, the best is **0.5**, lower than ARC's number for the same answers.
- **Per Check** takes, for each grid, whichever Attempt got it right: **1.0**, ARC's number.

On a Benchmark with one Check per Case, which is every Imported Benchmark, the two rules give
the same score.

**Any-match needs pass/fail Checks.** A Check graded 0.6 (an F1, a partial rubric) is neither
met nor missed in the published sense, and inspect's `max` would take the larger partial score,
which no ARC or ZeroBench paper reports. So an Attempt whose Case Grade has a Check score other
than 0 or 1 fails the Case with the named failure `attempt_grade_not_pass_fail`, never a guess.

### 2.5 What the Report and the Leaderboard see

The Case Result gains `attempts`: one entry per Attempt, carrying its answer, finish reason,
failures and Case Grade. It is absent when N = 1, so every existing report.json is unchanged.
The Case Result's own `output` and `grade` stay what a reader and the Aggregation already read:
the shown answer and the folded Case Grade.

The Aggregation is unchanged: the Headline Score is the mean of Case scores. The SDK Report adds
one line per Case, "1 of 2 Attempts matched", and the run's cost includes every Attempt. The
Leaderboard ranks the Headline Score; since N is part of the Benchmark Revision, every entry on
one Leaderboard used the same N.

### 2.6 The importer: any-match epochs become Attempts, everything else is refused

| inspect Task declares | Example | Imported as |
|---|---|---|
| no epochs, or `epochs=1` with any reducer | every published Imported Benchmark; lab_bench's `Epochs(1, "mode")` | as today, no `attempts` |
| `epochs=N`, every reducer `max`, `at_least(1)` or `pass_at(N)` | an ARC-style any-of-N Task | `attempts=N` |
| `pass_at(k)` with k < N, `mean`, `median`, `mode` | MBPP (5 epochs, `pass_at_1`/`_2`/`_5`), b3, tac | refused, naming the reducer |
| `pass_k`, `at_least(k > 1)`, a custom reducer | ZeroBench's `5_of_5_reliability` | refused, naming the reducer |

Until the build lands, the importer refuses every `epochs` > 1 (D12), because there is nowhere
yet to send a second Attempt.

## 3. Architecture / Design

How to read this section: the circled numbers ① to ⑪ are the boxes of the Architecture map in
§3.3, one numbering for the whole spec, so ⑤ is the same code in the Data Flow, the Failure-modes
table and the delivery plan. Read the Data Flow first (one Case, two Attempts, end to end: *how*
it works), then the Failure modes (rows F1 to F8: *what breaks* and who notices), then the
Architecture map (*where*: which files, new or changed). Read each diagram's key before its
boxes.

### 3.1 Data Flow — one Case, two Attempts, an unseeded run

The example is illustrative: the Case "What is 6 times 7?", answer key `42`, on a Benchmark that
declares `attempts=2`.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 460}}}%%
flowchart TB
  s0["INPUT · the Case, frozen at Case Preparation (an example)<br/>e.g. input: What is 6 times 7? · answer key: 42 · attempts: 2"]
  s3["③ the per-Case step starts Attempt 1 of 2<br/>symbol · preserve_candidate_outcome · protocol.py<br/>🔀 WHEN & WHO: Attempts run in order, inside one Case"]
  s4a["④ ⑤ Attempt 1: the Candidate Invocation, request unchanged<br/>e.g. seed: none · cache: participates<br/>⏱ TIME: one full Candidate answer"]
  c1[("⑥ AI gateway exact-request cache<br/>💾 SPACE: shared by every hosted user<br/>e.g. no stored reply for this request")]
  p1["model provider<br/>e.g. reply: 41"]
  s7a["⑦ Grading, Attempt 1<br/>e.g. Check 1: UNMET · score: 0.0"]
  s4b["④ ⑤ Attempt 2: same prompt, cache opt-out<br/>e.g. seed: none · cache: use-cache false<br/>🧩 MEANING: the Candidate sees the same input"]
  p2["model provider<br/>e.g. reply: 42"]
  s7b["⑦ Grading, Attempt 2<br/>e.g. Check 1: MET · score: 1.0"]
  s8["⑧ the fold: a Check is met if any Attempt met it<br/>e.g. Check 1: MET by Attempt 2 · Case score: 1.0 · shown: Attempt 2"]
  r9[("⑨ Case Result in report.json<br/>e.g. output: 42 · score: 1.0<br/>attempts: 1 → 41, 0.0 · 2 → 42, 1.0<br/>💾 SPACE: the run's report")]
  s10["⑩ Aggregation, unchanged<br/>e.g. mean over 120 Cases → Headline Score 0.31"]
  s11["⑪ OUTPUT · the SDK Report<br/>e.g. Case 1: 1 of 2 Attempts matched"]
  s0 -->|the Engine loads the Case| s3
  s3 -->|asks the Candidate| s4a
  s4a -.->|🌐 gateway looks up the exact request| c1
  c1 -.->|🌐 miss: the gateway calls the provider| p1
  p1 -->|the reply comes back| s7a
  s7a -->|Attempt 2 starts| s4b
  s4b -.->|🌐 opt-out skips the cache, gateway calls the provider| p2
  p2 -->|the reply comes back| s7b
  s7b -->|both Case Grades| s8
  s8 -->|writes| r9
  r9 -->|one per Case| s10
  s10 -->|the SDK reads the report back| s11
  subgraph KEY["HOW TO READ — dashed arrows are network hops; circled numbers are §3.3's boxes"]
    direction LR
    k1["processing step"]
    k2[("record or store at rest")]
    k3["outside party"]
  end
  s11 ~~~ KEY
  classDef stage fill:#1e3a8a,stroke:#4a7fd4,color:#dbeafe
  classDef data  fill:#4c1d95,stroke:#a06ed4,color:#ede9fe
  classDef plain fill:#374151,stroke:#9ca3af,color:#f3f4f6
  class s0,s3,s4a,s4b,s7a,s7b,s8,s10,s11,k1 stage
  class c1,r9,k2 data
  class p1,p2,k3 plain
  style KEY fill:#111827,stroke:#6b7280,color:#f3f4f6
```

Tags inside a box name the limit that shapes it: ⏱ when it runs, 💾 where it rests, 🌐 a
network hop, 🔀 ordering, 🧩 the same bytes read differently. In a seeded run, Attempt 2 instead
carries a seed derived from the run's seed and may be served from the cache on a rerun (§2.3).

### 3.2 Failure modes

| # | Fault | Box | Who notices | Outcome |
|---|---|---|---|---|
| F1 | An inspect Task declares `epochs` > 1, before the build lands | ② | the importer | refused by name (D12) |
| F2 | An inspect Task declares epochs with a reducer we don't run (`mean`, `pass_at(k < N)`, a custom one) | ② | the importer | refused naming the reducer |
| F3 | Attempt 2 would be served Attempt 1's stored reply | ⑤ ⑥ | nobody, which is why §2.3 exists | prevented: Attempt 2's request always differs (a derived seed, or the cache opt-out) |
| F4 | One Attempt's Candidate Invocation or Grading fails, another is graded | ③ ⑧ | the Report | the Case is graded from the graded Attempts; the failed one keeps its failure in `attempts`; the Report says "1 of 2 Attempts failed" |
| F5 | Every Attempt of a Case fails | ⑧ | the Aggregation | the Case has no Case Grade; the Benchmark's Failure Policy applies, as today |
| F6 | An Attempt's Check is graded neither 0 nor 1 | ⑧ | the per-Case envelope | the Case fails as `attempt_grade_not_pass_fail`; no guessed fold |
| F7 | A seeded run names a Model whose provider has no `seed` | ⑤ | the SDK's parameter check, before any paid call | refused, as today for every seeded run |
| F8 | A researcher's SDK released before the build reads a report with `attempts` | ⑪ | the SDK decoder | "unsupported field"; reports without Attempts unaffected; the SDK slice releases first (§7) |

### 3.3 Architecture

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 440}}}%%
flowchart TB
  n1["① the Benchmark's cover sheet<br/>BenchmarkDeclaration · benchmarks/definition.py<br/>✏️ gains attempts, shown and pinned only when above 1"]
  n2["② the inspect importer<br/>importer.py · single_shot.py · screamingface_engine_inspect<br/>✏️ reads epochs: any-match becomes attempts, the rest refused"]
  n3["③ the per-Case step<br/>preserve_candidate_outcome · benchmarks/protocol.py<br/>✏️ runs ④ to ⑦ once per Attempt, in order"]
  n4["④ the Candidate Invocation<br/>_CandidateInvocation · world/candidate_adapter.py<br/>✏️ opens an Attempt scope holding the Attempt number"]
  n5["⑤ the model call leaving the Engine<br/>apply_answer_seed · world/request_parameters.py · world/connector.py<br/>✏️ Attempt 2 and later: derived seed, or the cache opt-out"]
  n6["⑥ the AI gateway exact-request cache<br/>GlobalChatCacheKey · apps/aigateway request_cache/global_keys.py<br/>unchanged: the reason ⑤ changes"]
  n7["⑦ the Benchmark's own Grading<br/>scorer adapter, rubric graders<br/>unchanged: runs once per Attempt"]
  n8["⑧ the per-Case envelope and the fold<br/>graded_answer.py<br/>✏️ accepts N outcomes, folds per Check"]
  n9["⑨ the Case Result on the wire<br/>CaseResult · benchmarks/contract.py<br/>✅ new attempts list, absent when N is 1"]
  n10["⑩ Aggregation<br/>finalize_candidate_result · benchmarks/aggregation.py<br/>unchanged: mean of Case scores"]
  n11["⑪ the SDK decoder and Report<br/>case_result.py · report.py · packages/screamingface<br/>✏️ decodes attempts, shows which matched"]
  n1 --> n2 --> n3 --> n4 --> n5 --> n6 --> n7 --> n8 --> n9 --> n10 --> n11
  subgraph KEY["HOW TO READ — colour is what the build does to the box"]
    direction LR
    k1["✅ new"]
    k2["✏️ changed"]
    k3["unchanged neighbour"]
  end
  n11 ~~~ KEY
  classDef good  fill:#14532d,stroke:#30a46c,color:#dcfce7
  classDef stage fill:#1e3a8a,stroke:#4a7fd4,color:#dbeafe
  classDef plain fill:#374151,stroke:#9ca3af,color:#f3f4f6
  class n9,k1 good
  class n1,n2,n3,n4,n5,n8,n11,k2 stage
  class n6,n7,n10,k3 plain
  style KEY fill:#111827,stroke:#6b7280,color:#f3f4f6
```

The arrows are the order a Case passes through the code, not imports. The stages that carry a
"because":

- ③ runs Attempts in order inside one Case, because Cases already run one at a time and the
  Case scope is what attributes each call's cost to its Case.
- ⑤ changes only Attempts 2 and later, because Attempt 1 byte-identical to today is what keeps
  every existing Benchmark's egress, replay fixtures and goldens unchanged.
- ⑧ folds per Check, because ARC-AGI-2 credits each test grid separately (§2.4).
- ⑨'s field is absent at N = 1, because the SDK decoder refuses unknown keys and every
  existing report must stay readable.

## 4. Known limitations of this design

- **N Attempts cost N times as much.** ARC-AGI-2 at two Attempts per grid is 334 Candidate
  Invocations for 120 tasks. Accepted: it is the published rule, and the catalogue states it.
- **An unseeded run cannot replay Attempts 2 and later from the cache**, so a rerun pays for them
  again. Accepted: a seeded run replays every Attempt; giving the shared cache a sampling member
  is a gateway decision (OME-305) this ticket does not reopen.
- **Attempts at temperature 0 come out nearly identical**, and the score is close to the
  first-Attempt score. Accepted: the Candidate owns its sampling settings, and the ARC harness
  behaves the same way; the Report shows the identical answers.
- **Only any-match is supported.** MBPP (pass@1 estimated from 5 samples) and ZeroBench's
  all-must-match reliability stay refused by name until a Benchmark needs them.
- **A Case with a failed Attempt has fewer chances to pass** (F4). Accepted: the ARC harness
  counts a missing Attempt the same way; the Report says how many Attempts failed.
- **How ARC-AGI-2 prompts each test grid is OME-1476's design.** The harness sends one prompt per
  grid; that Benchmark will need one Candidate Invocation per grid per Attempt, which the
  glossary already allows ("a Case may require multiple ordered Candidate Invocations").

## 5. Out of scope

- pass@1-from-N, all-must-match and mean-over-Attempts folds (D2).
- A sampling member in the AI gateway's cache key.
- A Cost Estimate (ADR 0003); question 5's ×N waits for it.
- ARC-AGI-2 itself (OME-1476) and ZeroBench (needs image input).
- Any Leaderboard or Scoreboard column for per-Attempt detail.

## 6. Acceptance

1. A Benchmark without Attempts is byte-identical: every published Benchmark Revision unchanged
   (`test_published_revisions.py` untouched), every e2e golden green including its
   `expression_sha` rung, and Attempt 1's egress identical to today's.
2. A test-only Benchmark declaring `attempts=2` runs end to end locally against stubbed replies
   `41` then `42`: its Case Result carries both Attempts, the Case scores 1.0, and the Report
   prints "1 of 2 Attempts matched".
3. A two-Check fixture where Attempt 1 meets only Check A and Attempt 2 only Check B scores 1.0
   (the ARC rule), pinned by a test that says why.
4. Attempt 2's request differs from Attempt 1's in an unseeded run (the cache opt-out) and in a
   seeded run (a different seed), pinned by tests on the request the Engine sends.
5. The importer maps `max`, `at_least(1)` and `pass_at(N)` to `attempts=N` and refuses every
   other reducer by name; before the build, it refuses every `epochs` > 1 (OME-1458, PR 2).
6. A non-0/1 Check under Attempts fails the Case as `attempt_grade_not_pass_fail`, pinned on both
   the Engine and SDK failure-code lists.

## 7. Delivery

| PR | Ticket | Lands in | Carries |
|---|---|---|---|
| this one | OME-1458, PR 1 of 2 | `docs/` | this spec, the `Attempt` glossary entry, ledger and mirror |
| next | OME-1458, PR 2 of 2 | `apps/screamingface-engine` | ② refuses every `epochs` > 1 by name (F1) |
| build 1 | new ticket | `packages/screamingface` | ⑪ decoder accepts `attempts`, the Report line, the new failure code; released first (F8) |
| build 2 | new ticket | `apps/screamingface-engine` | ① ③ ④ ⑤ ⑧ ⑨: the declaration, the Attempt loop, Attempt 2's request, the fold, the wire field, the test-only Benchmark |
| build 3 | new ticket | `apps/screamingface-engine` | ② maps any-match epochs to `attempts=N` and narrows F1 to F2 |

Deploy order: the SDK from build 1 releases before the Engine from build 2 deploys, the order
OME-1268 used. Build 2 may split in two if it passes the ~500-line review cap; the seam is ⑤
(Attempt 2's request) versus ⑧ ⑨ (the fold and the wire).

## 8. Glossary

`CONTEXT.md` gains one entry in this PR:

- **Attempt**: one complete, independent answer by the Candidate to a Case, graded on its own.
  A Benchmark that declares N Attempts asks each Case N times; a Check is met if any Attempt met
  it. _Avoid_: epoch (inspect's word), sample, try, retry (a retry re-sends one failed request),
  pass@k (inspect's `pass_at` is an estimator, a different number).
