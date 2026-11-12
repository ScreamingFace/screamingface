# PRD: Cascade — cheap first, escalate only when a line says so

**Source:** epic OME-1291 behavior 2, ans:Q6, ans:Q7, ans:Q17, OME-1465, OME-1630; owner review
2026-11-12 (Irina's product review)
· **Priority:** P0 (PR-1)
**Lifecycle:** planned (a new public shortcut function over [gate](gate.md))
**Owner:** unassigned
Paths: [erd §1, §3, §4](../erd.md) · contracts: C1–C4 · component: [branch-core](branch-core.md),
[gate](gate.md) · budget interplay: [budget](budget.md) · display: [report](report.md)

## 1. Summary and user story

As a researcher whose result is a saving, I want to write "run the cheap tier; call the next tier
only when this line holds", one line per escalation, so that the expensive model runs only on the
Cases that need it, the recipe says each reason to escalate, and the report shows the share of
Cases that stayed on the cheap tier.

`sf.Cascade(t1, sf.escalate_if(c1), t2, sf.escalate_if(c2), t3)` is a shortcut function. The
tiers are positional arguments, read top to bottom. Each escalation is its own line,
`sf.escalate_if(condition)`, between the two tiers it connects. The optional last part is
`sf.abstain()` or `sf.fail()` after a line. The function returns ordinary nested `sf.Gate` values
(ans:Q6), the way `sf.Fusion` returns the `sf.Fanout(...) >> S` chain. It has no compile path of
its own. [stated owner 2026-11-12 — supersedes the list form
`sf.Cascade([s1, s2, s3], escalate_if=c, otherwise=None)`]

```python
sf.Cascade(
    sf.Fanout([small], signals={"lp": sf.Logprob("prob")}) >> sf.Vote(),
    sf.escalate_if(sf.signal("lp").chosen() < 0.7),
    large,
)
```

## 2. Background and constraints

- "Run the first stage. Compute a declared comparison. If it passes, return that stage's answer
  and do not call the later stages. If it fails, call the next stage on the original question,
  not on the previous answer. Repeat until a stage passes or the list ends." [stated epic]
- "Stage 1 always runs." "Stage k+1 runs only if stage k's escalate condition is true." [stated epic]
- "Each stage's prompt input is the original user question (plus whatever the recipe attaches),
  not 'here is the previous model's answer, please continue.'" [stated epic]
- "The condition is a comparison the author wrote against a declared signal: `confidence < 0.7`,
  `agreement < 0.8`. It is data." [stated epic]
- "The signal is E4b. This epic does not define how confidence is measured. It defines the skip."
  [stated epic]
- "Human as the last tier: if every model tier escalates, the outcome is abstain, not a made-up
  answer. The report counts it as declined." [stated epic]
- STEER: "v1 is per full answer. Per-token escalation inside a single decode is out of scope."
  [stated epic]
- Cascade is sugar over nested Gates. [stated ans:Q6]
- Adaptive sampling is a Cascade over sample panels; no sample reuse; documented; the incremental
  top-up stays OME-1630. [stated ans:Q7]
- **Superseded.** ans:Q17 said "a stage that fails or abstains escalates", with optional members
  and url4 `quorum=0` on every gated stage. The owner reversed it on 2026-11-12: nothing escalates
  unless a line says so. A tier with a condition line keeps its `sf.Fanout` as the author wrote
  it. A failed tier fails the Case, an abstained tier makes the Case abstain, and a missing number
  fails the Case with `signal_missing`. Only `sf.escalate_if(sf.unanswered())` escalates on a
  failure or an abstain. [stated owner 2026-11-12 — supersedes ans:Q17]
- **Superseded.** ans:Q24 said "a gated stage where only some members fail decides on the members
  that answered". The owner reversed it on 2026-11-12: the tier's `sf.Fanout` quorum decides. With
  `quorum="all"` (the default) one failed member fails the Case with that member's code. The
  author writes `quorum=2` to decide on the rest. [stated owner 2026-11-12 — supersedes ans:Q24]
- The rule lives in the Engine's Gate, not in `sf.Cascade`. So it applies to every `sf.Gate`
  whose `otherwise=` is a recipe ([gate](gate.md) GT-28, GT-29; [branch-core](branch-core.md)
  D4). [stated owner 2026-11-12]
- Today `quorum="all"` compiles to url4 `quorum = len(members)` [existing
  `S/_evaluation/candidate.py:403`]; a failed optional slot does not count, and below the quorum
  url4 raises `QUORUM_NOT_MET` for the whole group [existing `U/dag/nodes/_shared.py:221-224`,
  `:255-261`]. So optional members alone cannot make a tier escalate; the
  `sf.escalate_if(sf.unanswered())` tier also takes url4 `quorum=0` (CA-10).
- OME-1465: "an early-termination mode where the first member/branch to succeed 'trumps' the
  others and the remaining branches are not run"; sequential form only. [stated ans:Q5]
- OME-1630: "early-stopping and dynamic reallocation of samples/compute based on intermediate
  results"; via a Cascade over sample panels. [stated ans:Q7]

### 2.1 Current behavior (the pieces the shortcut reuses)

- `sf.Fusion` is a function that returns the ordinary chain; "no second compile path: the result
  is the chain that `sf.Fanout(members, ...) >> S` builds, so it compiles to the same bytes"
  (`S/_surface/fusion.py:1-8`, `:33-64`) [existing]. This PRD copies that pattern.
- `sf.Gate(when=, then=, otherwise=, abstain_if=)` closes a block; `then` must be a `sf.Vote`
  "until E4c" (`S/_surface/gate.py:86-92`) [existing]; [gate](gate.md) widens it (ans:Q6).
- A gate condition is `GateRef <cmp> threshold`, cmp in `>=`, `>`, `<=`, `<`
  (`S/_surface/refs.py:50-95`). The stored form is the KEEP form: the condition that keeps the
  answer; an agreement gate accepts only `>=` or `>` with a threshold in [0, 1]
  (`S/gate.py:152-161`) [existing].
- `passes(None, cmp, threshold)` is False (`E/combine/gate.py:73-75`): in E4b a missing number
  takes the fallback branch [existing]. E4c keeps this for every gate whose `otherwise` is not a
  recipe; a recipe `otherwise` fails the Case with `signal_missing` instead (CA-31).
- `sf.Fanout(members, signals=, quorum=, name=, prompt=)`; a member may be `optional=True`
  (`S/_surface/fanout.py:24-60`; `S/model.py:26-43`) [existing]. `quorum` is the successful-member
  floor, `"all"` or 0..n (`S/fusion.py:399-405`) [existing].
- `sf.samples(model, n, seeds=None, …)` builds n Models that differ in `seed`; the default seeds
  are `0..n-1` (`S/_samples.py:21-51`, `:62-75`) [existing].
- No `sf.Cascade` exists [existing].

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **CA-1 The shortcut builds nested Gates.** Given
  `sf.Cascade(t1, sf.escalate_if(c), t2, sf.escalate_if(c), t3)` where
  `t1 = sf.Fanout(A) >> sf.Vote()` and `t2 = sf.Fanout(B) >> sf.Vote()`, When it is built, Then the
  result equals `sf.Fanout(A) >> sf.Gate(when=keep(c), then=sf.Vote(), otherwise=sf.Fanout(B) >>
  sf.Gate(when=keep(c), then=sf.Vote(), otherwise=t3))`. A condition line does not change the
  tier's members or its quorum. `==`, `repr` and `Url4.to_python()` show this Gate form.
  [stated ans:Q6; stated owner 2026-11-12; proposed — `S/_surface/fusion.py` exemplar]
- **CA-2 Tier 1 passes: later tiers make zero calls.** Given tier 1's keep condition holds, When
  the Case runs, Then the answer is tier 1's reducer answer, tiers 2..n make zero model calls, and
  the outer Gate's decision record lists `otherwise` as `not_selected`. [stated epic]
- **CA-3 Escalation answers the original question.** Given tier 1's keep condition fails, When
  tier 2 runs, Then tier 2's members receive the Cascade's input (the Case input when the Cascade
  is the root or a first stage) and never tier 1's answers. [stated epic; branch-core BC-5]
- **CA-4 Polarity.** Given `sf.escalate_if(ref < x)`, Then the Gate keeps with `ref >= x`; `<=` →
  `>`; `>` → `<=`; `>=` → `<`. The decision record and the report show the author's escalate form
  next to the stored keep form. [proposed — `S/_surface/refs.py` keep form, E4b P4]
- **CA-5 Per-tier conditions.** Given `sf.Cascade(t1, sf.escalate_if(c1), t2,
  sf.escalate_if(c2), t3)`, Then tier 1's Gate reads `c1` and tier 2's Gate reads `c2`. Each line
  holds the condition of the tier above it; there is no shared condition and no count to check.
  [stated owner 2026-11-12 — supersedes the list form `escalate_if=[c1, c2]`]
- **CA-32 A bare signal is refused in a condition.** Given `sf.escalate_if(sf.signal("lp") < 0.7)`
  or `sf.Gate(when=sf.signal("lp") >= 0.7, ...)`, Then `TypeError` before any call: "sf.escalate_if
  cannot read a bare signal: write sf.signal('lp').chosen() < 0.7 (the chosen member's value) or
  sf.signal('lp').mean() < 0.7 (the mean over the members). A bare sf.signal(...) comparison is the
  per-member test of sf.Filter." WHY: one expression keeps one meaning, and the author picks
  `.chosen()` or `.mean()` (the two can take different branches). `sf.Filter(where=...)` keeps the
  bare form. [stated owner 2026-11-12, round 2 — supersedes the bare-signal reading of the same day]
- **CA-6 A failed tier with a condition line fails the Case.** Given a tier with a condition line
  whose `sf.Fanout` has `quorum="all"` (the default), When one member fails (refusal, token cap),
  Then url4 fails the panel and the Case fails with that member's own failure code; the next tier
  makes zero calls. `sf.Cascade` keeps the tier's `sf.Fanout` exactly as the author wrote it: no
  optional members, no url4 `quorum=0`. [stated owner 2026-11-12 — supersedes ans:Q17]
- **CA-29 The tier's quorum decides a partial failure.** Given a tier with a condition line, three
  members and `quorum=2`, When one member fails and two answer, Then the decision call reduces over
  the two answers (agreement over 2 votes, the mean over their signals) and the gate compares as
  usual; the tier escalates only when that comparison fails. With `quorum="all"` the same Case
  fails (CA-6). [stated owner 2026-11-12 — supersedes ans:Q24]
- **CA-7 An abstained tier with a condition line abstains the Case.** Given a tier with a
  condition line whose reducer abstains (`no_votes`, `cut_not_met`, `output_missing`), When the
  Case runs, Then the gate did not run (`branch` null in the E4b gate record), nothing escalates,
  and the Case abstains with that reason, copied by JOIN ([branch-core](branch-core.md) D4, D12).
  [stated owner 2026-11-12 — supersedes ans:Q17]
- **CA-31 A missing number fails the Case with `signal_missing`.** Given a tier with a condition
  line on a number that a reply does not carry (for example `sf.signal("lp")` on a reply with no
  log-probability), When the Case runs, Then the E4b gate record takes `fallback` on the missing
  value (observed null), DECIDE raises the new permanent failure `signal_missing` ("sf.Gate gate_N
  read a missing number, so it can neither keep the answer nor escalate"), the next tier makes
  zero calls, and the Case fails with code `signal_missing`. [stated owner 2026-11-12;
  [branch-core](branch-core.md) D4a]
- **CA-8 The last tier answers unconditionally by default.** Given no outcome part, Then the last
  tier is any recipe (a route string, `sf.Model`, chain, Gate) and its answer is final; its
  failure fails the Case. [stated ans:Q17 — this part stands; proposed default]
- **CA-9 Human as the last tier.** Given `sf.Cascade(t1, sf.escalate_if(c1), t2,
  sf.escalate_if(c2), sf.abstain())`, Then the last tier `t2` is gated too, and when its keep
  condition fails the Case abstains with `gate_not_met`, scored 0 and counted as declined. The
  innermost JOIN writes the abstain and every outer JOIN copies it from its `otherwise` terminal,
  so it reaches the root ([branch-core](branch-core.md) D12, BC-36). `sf.fail()` in the same place
  fails the Case with `fail_closed`. [stated epic; stated owner 2026-11-12 — supersedes
  `otherwise="abstain"` / `"fail_closed"`; proposed — erd §6 reason reuse; review 3 F1]
- **CA-30 A gated last tier gives no answer.** Given a last tier that is gated (an outcome part
  follows its line), When the tier gives no answer, Then the rules of CA-6, CA-7 and CA-31 apply as
  for any tier with a condition line: a member failure fails the Case as the tier's quorum says,
  an abstained reducer makes the Case abstain with its reason, and a missing number fails it with
  `signal_missing`. Only after `sf.escalate_if(sf.unanswered())` (members optional, url4
  `quorum=0`) does the decision call find no voters; then the branch-core D4 null row applies:
  with `sf.abstain()` the Case abstains `no_votes` (scored 0, declined), and with `sf.fail()` JOIN
  raises `fail_closed` and the Case fails with that code. [stated owner 2026-11-12; proposed —
  review 3 F7]
- **CA-10 First-success (OME-1465, sequential).** Given `sf.Cascade("prov/a",
  sf.escalate_if(sf.unanswered()), "prov/b", sf.escalate_if(sf.unanswered()), "prov/c")`, Then
  each tier escalates only when it failed or abstained, the Cascade returns the first tier's answer
  that exists, and later tiers make zero calls. A route string or `sf.Model` tier before an
  `sf.unanswered()` line becomes `sf.Fanout([m]) >> sf.Vote()`, and its output is the member reply
  byte for byte. `sf.Cascade` marks that tier's members `optional=True`, compiles its panel with
  url4 `quorum=0` (the consistency precedent [existing `S/_evaluation/candidate.py:761-800`]), and
  stores the keep condition `sf.answered()`. A null branch maps to `otherwise` only for this
  condition ([branch-core](branch-core.md) D4). [stated ans:Q5; stated owner 2026-11-12]
- **CA-11 Adaptive sampling (ans:Q7).** Given `sf.Cascade(sf.Fanout(sf.samples(m, 2)) >>
  sf.Vote(), sf.escalate_if(sf.agreement() < 1.0), sf.Fanout(sf.samples(m, 5, seeds=range(2, 7)))
  >> sf.Vote())`, Then two samples run on every Case and five fresh samples run only when the two
  disagree; the escalated Case pays 2 + 5 calls; tier 2 does not reuse tier 1's samples. The docs
  state this and point to OME-1630 for the incremental top-up. [stated ans:Q7]

### 3.2 Error paths (refused when the shortcut is called, before any run)

- **CA-12 Parts in the wrong order.** The parts go tier, line, tier, line, …, and end on a tier or
  on an outcome after a line. [stated owner 2026-11-12 — supersedes "fewer than two stages"]
  - Two tiers with no line between them, or an outcome right after a tier →
    `ValueError("sf.Cascade part N can never run: write sf.escalate_if(...) after tier K")`.
  - A line first, or two lines in a row → `ValueError("sf.escalate_if(...) goes between two
    sf.Cascade tiers")`.
  - Any part after `sf.abstain()` or `sf.fail()` → `ValueError("sf.abstain() or sf.fail() is the
    last part of a sf.Cascade")`.
  - An outcome first → `ValueError("a sf.Cascade starts with a tier")`.
  - No line, or a Cascade that ends on a line (`sf.Cascade(t1)`, `sf.Cascade()`,
    `sf.Cascade(t1, sf.escalate_if(c))`) → `ValueError("sf.Cascade needs a tier, an
    sf.escalate_if(...) line, and a tier, sf.abstain() or sf.fail() after it")`.
- **CA-13 A tier before a condition line that is not a block ending in a reducer step.** A tier
  before a condition line that is a route string or `sf.Model`, a Fanout with no reducer, a chain
  that ends in `sf.Synthesize`, or a narrow step at the end → `TypeError("a cascade tier before an
  sf.escalate_if line must end in a reducer step such as sf.Vote(): write sf.Fanout([m],
  signals=...) >> sf.Vote()")`. A route string or `sf.Model` is accepted before an
  `sf.unanswered()` line (CA-10). [proposed; stated owner 2026-11-12]
- **CA-14 Undeclared signal.** `sf.escalate_if(sf.signal("conf").chosen() < 0.7)` after a tier whose Fanout
  does not declare `conf` → the E4b declared-name refusal, prefixed `sf.Cascade tier N: `.
  [existing rule `S/gate.py:126-137`; proposed tier number in the message]
- **CA-15 Agreement with an inverted keep form.** `sf.escalate_if(sf.agreement() >= 0.8)`
  (escalate on high agreement) → the keep form `agreement < 0.8` is refused by the E4b agreement
  rule; the message names the tier and the line the author wrote
  (`sf.Cascade tier N: sf.escalate_if(agreement() >= 0.8): …`). [existing `S/gate.py:152-161`]
- **CA-16 The list form is refused.** `sf.Cascade([t1, t2])` (one list or tuple argument) →
  `TypeError("sf.Cascade takes its tiers as arguments, with a line between each two:
  sf.Cascade(t1, sf.escalate_if(...), t2)")`. The keywords `escalate_if=` and `otherwise=` do not
  exist, so Python raises its own `TypeError` (unexpected keyword argument). There is no alias:
  the list form was never released. [stated owner 2026-11-12 — supersedes the old CA-16 arity
  check "one condition or one per gated stage"]
- **CA-17 Numeric quorum on an `sf.unanswered()` tier.** A tier before an
  `sf.escalate_if(sf.unanswered())` line with `quorum=N` → `ValueError("an
  sf.escalate_if(sf.unanswered()) tier decides on the members that answered; it takes
  quorum='all'")`, because that tier is compiled with url4 `quorum=0`, and a numeric floor would be
  a second, conflicting rule. A tier before a condition line takes any quorum (CA-29). [proposed —
  gap §per-connection; stated owner 2026-11-12 — the refusal no longer applies to condition lines]
- **CA-18 Bad part or bad line.** A part that is not a tier (a route string or a recipe), a line
  or an outcome → the CA-16 `TypeError`. `sf.escalate_if(x)` where `x` is not a condition →
  `TypeError("sf.escalate_if takes a condition such as sf.agreement() < 0.8, sf.signal('lp') < 0.7
  or sf.unanswered()")`. The string `"fail_closed"` as the last part is read as a tier and is then
  refused by `sf.Gate` ([gate](gate.md) GT-12). [stated owner 2026-11-12 — supersedes "anything
  but None, 'abstain' or 'fail_closed'"]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| CA-19 | Every tier fails | [stated owner 2026-11-12 — supersedes ans:Q17] | H×M | Given condition lines and every tier's members fail, Then tier 1's failure fails the Case with tier 1's member code and tiers 2..n make zero calls. Given `sf.unanswered()` lines and no outcome part, Then tiers 1..n-1 escalate and the Case fails with the last tier's own failure code. |
| CA-20 | Every tier escalates, `sf.abstain()` last | [stated epic] | H×M | Given every keep condition fails, Then all n tiers ran once each and the Case abstains `gate_not_met` (the root JOIN copies the innermost abstain, branch-core BC-36); the report counts it declined. |
| CA-21 | Same bytes as hand-written Gates | [implied — ans:Q6] | H×M | Given the CA-1 Cascade and the equal hand-written Gate chain, Then both compile to byte-identical url4. |
| CA-22 | Rebuild shows the Gate form | [proposed] | M×M | Given the Cascade's url4, When `Url4.to_python()` runs, Then the code has nested `sf.Gate(...)` (with `sf.abstain()` / `sf.fail()` for an outcome) and no `sf.Cascade`; it recompiles to the same bytes (RB-1). |
| CA-23 | Default sample seeds collide | [proposed — gap §edge] | M×M | Given tier 2 uses `sf.samples(m, 5)` with default seeds after tier 1's `sf.samples(m, 2)`, Then the shortcut emits `CascadeSeedWarning` ("sf.Cascade tier 2 repeats seeds 0, 1 of tier 1; give seeds= for fresh samples"), because equal requests can be gateway cache hits with the same text. |
| CA-24 | An optional member the author already marked | [proposed] | L×M | Given an `sf.unanswered()` tier with a member already `optional=True`, Then it stays optional and nothing else changes. A tier before a condition line is never changed. |
| CA-25 | Nested Cascade in a branch | [stated ans:Q10] | M×L | Given a Cascade as `then=` of an input Gate, Then it compiles (depth counts toward the 8-Gate cap, branch-core BC-18). |
| CA-26 | Cascade as a Pipeline stage | [stated ans:Q10] | M×L | Given `cascade >> sf.Synthesize(w)`, Then the writer reads the Cascade's final answer; the Cascade tiers still read `$input`. |
| CA-27 | Token-level escalation is refused by design | [stated epic non-goal] | L×L | The docs state that `sf.Cascade` decides per full answer; no API takes a token position. (Doc test only.) |
| CA-28 | `isinstance` | [proposed] | L×L | `sf.Cascade` is a function; the docstring says `isinstance(x, sf.Cascade)` is not supported (as `sf.Fusion`). |

## 4. Non-functional requirements

- Engine code: a Cascade runs only branch-core endpoints and E4b combine calls, but the Gate rule
  of §2 needs two Engine changes in DECIDE (`E/world/branch.py`) [stated owner 2026-11-12 —
  supersedes "No new Engine code"]:
  1. `_panel_choice`: a null panel branch (no voters, or the combine abstained before the gate)
     maps to `otherwise` only when the gate condition is `sf.answered()` (observe `answered`) and
     `otherwise` is a recipe; for every other condition the Gate abstains with the decision call's
     reason ([branch-core](branch-core.md) D4).
  2. `_decide`: a panel gate whose E4b record took `fallback` on a missing number (`_Choice.missing`)
     and whose `otherwise` is a recipe raises `signal_missing(gate_id)`
     (`E/benchmarks/failure_classes.py`). The declared failure-code vocabulary grows by one
     (`E/benchmarks/contract.py`, `E/error_text.py`, `S/_report_primitives.py`): 68 → 69.
- Cost: a Case that passes at tier 1 pays exactly tier 1's calls plus zero model calls for the
  rest (the branch-core guarantee) [stated epic]. A Case that fails or abstains at a tier with a
  condition line makes zero calls after that tier [stated owner 2026-11-12].
- Observability: the report shows per Case the tier that answered and per run the share of Cases
  answered at each tier — CARGO's "fraction of calls that stay local" [stated epic; owned by
  [report](report.md)].
- Budget: a refused escalation keeps the current tier's answer, owned by [budget](budget.md)
  [stated ans:Q3].

## 5. Out of scope

- Per-token escalation inside one decode (STEER's inner loop) [stated epic].
- Parallel race that cancels slower branches (OME-1465 race form) [stated ans:Q5].
- Incremental sample top-up that reuses earlier samples (OME-1630) [stated ans:Q7].
- A tier that conditions on the previous tier's answer (that is today's Pipeline) [stated epic].
- Numeric quorum on an `sf.unanswered()` tier (CA-17) [proposed].
- Escalation on a failure or an abstain after a condition line (only `sf.unanswered()` escalates
  on those; see §6) [stated owner 2026-11-12].
- The list form `sf.Cascade([...], escalate_if=..., otherwise=...)` and any alias for it
  [stated owner 2026-11-12].

## 6. Open questions

- **OPEN — "escalate on failure OR on a low score".** Irina's review page flagged a tier that must
  escalate both when it fails or abstains and when its number is low. Today one line holds one
  condition: `sf.escalate_if(sf.unanswered())` escalates on no answer, and a condition line
  escalates on a low number but fails or abstains the Case on no answer. There is no spelling for
  both in one line yet. Owner decision needed: a combined condition (for example
  `sf.unanswered() | (sf.signal("lp") < 0.7)`), or no support. [stated owner 2026-11-12]

The cross-PRD items (`sf.answered()` in erd §1 and [gate](gate.md); the null-branch rule and the
missing-number rule in [branch-core](branch-core.md) D4, D4a) are resolved there.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in on the shortcut (pure SDK, cheap) then the Engine-world runs, because CA-21
(same bytes as hand-written Gates) makes every run test a test of [gate](gate.md), which comes
first in the build. RED first, always.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `agreement_keep_form_refuses_less_than` (E4b P4: an agreement gate keeps the majority with `>=` / `>` only) | unit | [existing `S/gate.py:152-161`] | H×M | passes today |
| 2 | `tier_one_passes_and_later_tiers_make_zero_calls` (Engine world, fake gateway counts calls per binding) | integration | CA-2 | H×H | shortcut + gate |
| 3 | `escalated_tier_reads_the_case_input_not_the_previous_answer` | integration | CA-3 | H×H | recipe body `$input` |
| 4 | `failed_tier_with_a_condition_line_fails_the_case` (the member's own code; the next tier makes zero calls) | integration | CA-6 | H×H | tier Fanout kept as written; url4 quorum |
| 5 | `abstained_tier_with_a_condition_line_abstains_the_case` (`no_votes`, `cut_not_met`) | integration | CA-7 | H×H | D4 null row: no `otherwise` unless `sf.answered()` |
| 5a | `missing_signal_fails_with_signal_missing` (a reply with no log-probability under `sf.signal("lp")`) | integration | CA-31 | H×H | `_decide` raises `signal_missing(gate_id)` (D4a) |
| 6 | `tier_quorum_decides_a_partial_failure` (`quorum=2`: decide on the two; `quorum="all"`: the Case fails) | integration | CA-29, CA-6 | H×M | url4 panel quorum as written |
| 7 | `cascade_equals_the_hand_written_nested_gates` | unit | CA-1 | H×H | `S/_surface/cascade.py` `Cascade` |
| 8 | `cascade_compiles_to_the_same_bytes_as_nested_gates` | unit | CA-21 | H×M | no own compile path |
| 9 | `escalate_form_maps_to_the_keep_form` (parametrized over the four cmps) | unit | CA-4 | H×M | `_keep(cond)` |
| 9a | `test_e4c_bare_signal_refused.py` (bare comparison in `sf.Gate` / `sf.escalate_if` → `TypeError` naming `.chosen()` and `.mean()`; `sf.Filter` keeps it) | unit | CA-32 | H×M | `refuse_bare_signal` in `S/_surface/refs.py` |
| 10 | `every_tier_escalates_and_the_case_abstains_gate_not_met` | integration | CA-9, CA-20 | H×M | innermost `otherwise` word; outer JOINs copy the `terminal` result (branch-core D12) |
| 11 | `every_tier_fails` (condition lines: tier 1's code; `sf.unanswered()` lines: the last tier's code) | integration | CA-19 | H×M | last tier keeps required members |
| 11a | `gated_last_tier_with_no_voters_follows_the_outcome` (`sf.unanswered()` line; `sf.abstain()` → abstain `no_votes`; `sf.fail()` → Case failed `fail_closed`) | integration | CA-30 | H×M | branch-core D4 null rows |
| 12 | `unanswered_line_escalates_on_failure` (first success returns the first answer verbatim) | integration | CA-10 | H×M | `sf.answered()`; auto-wrap; optional members, url4 `quorum=0` |
| 13 | `adaptive_sampling_pays_two_or_two_plus_five` | integration | CA-11 | M×M | — |
| 14 | `each_line_holds_its_own_condition` | unit | CA-5 | M×M | one line per tier |
| 15 | `two_tiers_with_no_line_are_refused` (parametrized over every CA-12 order refusal) | unit | CA-12 | M×M | `_parts` |
| 15a | `list_form_is_refused` (one list or tuple argument; `escalate_if=` keyword) | unit | CA-16 | M×M | `_FORM` |
| 16 | `tier_without_a_reducer_is_refused` (parametrized: Model before a condition line, open Fanout, Synthesize end, narrow end) | unit | CA-13 | M×M | tier shape check |
| 17 | `undeclared_signal_names_the_tier` | unit | CA-14 | M×M | message adds tier number |
| 18 | `inverted_agreement_escalation_is_refused` | unit | CA-15 | M×L | E4b rule via keep form |
| 19 | `numeric_quorum_on_an_unanswered_tier_is_refused` (a condition-line tier with `quorum=2` is accepted) | unit | CA-17 | M×L | `_optional_fanout` |
| 20 | `escalate_if_takes_a_condition_and_parts_take_a_tier_line_or_outcome` | unit | CA-18 | M×L | `_LINE_TYPE`, `_FORM` |
| 21 | `to_python_writes_nested_gates_and_recompiles` | unit | CA-22 | M×M | rebuild via gate |
| 22 | `default_seed_collision_warns` | unit | CA-23 | M×M | `CascadeSeedWarning(EvaluationWarning)` |
| 23 | `author_optional_member_is_unchanged` | unit | CA-24 | L×M | — |
| 24 | `cascade_in_a_branch_counts_toward_the_depth_cap` | unit | CA-25 | M×L | — |
| 25 | `cascade_then_synthesize_reads_the_final_answer` | integration | CA-26 | M×L | — |
| 26 | `cascade_docstring_states_per_answer_and_no_isinstance` | unit | CA-27, CA-28 | L×L | doc test |

Pinned files: `ST/public_surface_snapshot.json` (new names `Cascade`, `escalate_if`, `unanswered`,
`abstain`, `fail`; new warning `CascadeSeedWarning`) — owner approval at the PR.
