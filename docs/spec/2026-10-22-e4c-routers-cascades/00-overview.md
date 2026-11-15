# E4c: choose whether a model runs (gates, cascades, selectors, guards, budget) — overview

**Status:** draft, written from the owner interview of 2026-10-22 (Q1–Q26); review round 1
(Opus, ESCALATE: 1 blocker, 10 major), review round 2 (Opus, ESCALATE: 2 blockers, 5 major) and
review round 3 (targeted Opus, ESCALATE: 1 blocker, 4 major) fixed. Owner approved P1–P32 as written on 2026-10-22; build of all three PRs started. **Epic:** E4c (OME-1291). **Leaves:** filed at PR-open.
**Base:** branch `e4c-routers-cascades`, worktree `.claude/worktrees/e4c-routers-cascades`, on ref
`e4b-integrated` (`031780873` = origin/main `bdf5746a4` + the E4b stack #1409, #1460, #1461
merged). When E4b lands on main: `git rebase --onto origin/main e4b-integrated`.

## 1. Summary

Today every model in a recipe runs. `Fusion` calls every member; `Pipeline` calls every stage;
the E4b gate records its choice, but its fallback call still runs on every Case. Epic OME-1291
asks: "A model that appears in the recipe might not be called. The recipe decides, from the
question or from a number on an answer already produced, and only the chosen work runs." The
one rule: "a branch that is not selected makes zero model calls, and the report says it was not
selected and why."

E4c ships one branch construct and the pieces it reads:

- **`sf.Gate` is the general branch** (ans:Q6, ans:Q9): `sf.Gate(when=…, then=…, otherwise=…)`.
  `then`/`otherwise` take a reducer step (after a panel), a whole recipe, or an outcome
  (`sf.abstain()`, `sf.fail()`; owner 2026-11-12, §5.1). An N-way router is nested binary Gates (ans:Q12). A Gate may be the root, a
  Pipeline stage or a branch (ans:Q10).
- **The skip is real** (ans:Q1): every branch body sits in a gated url4 `iterate` behind an Engine
  endpoint that returns a 0-or-1-item collection; an empty collection runs nothing (url4 Spec B
  §5.3.9). The E4b gate fallback becomes lazy with no evidence change.
- **`sf.Cascade`** is sugar for nested Gates: `sf.Cascade(t1, sf.escalate_if(c), t2)`. The cheap
  tier runs first, and the next tier runs only when the `sf.escalate_if` line before it holds.
  Nothing escalates unless a line says so: a failed tier fails the Case, an abstained tier makes
  it abstain, and a missing number fails it with `signal_missing`; only
  `sf.escalate_if(sf.unanswered())` escalates on no answer (owner 2026-11-12, §5.1). Adaptive
  sampling is a Cascade over sample panels (ans:Q7).
- **Selectors:** `sf.RegexClassifier` (RE2, no model) and `sf.LLMClassifier` (one cheap call), single or
  multi; read by `sf.label(sel) == / != "x"` and `sf.labels(sel).has("x") / .empty()` (ans:Q8).
- **Set-valued choice:** a skip-Gate (no `otherwise`) as a Fanout member (ans:Q16).
- **Guards** are outer Gates on a RegexClassifier or LLMClassifier label (ans:Q15) with `then=sf.fail()`
  (the new failure code `fail_closed`) or a stronger branch; a fired guard calls no model after it (ans:Q18).
- **Budget:** `sf.WithBudget(recipe, budget_usd=…, max_tokens=…)` once on the candidate (ans:Q19), per Case
  (ans:Q13); an optional branch whose author estimate would pass the cap is not sent (ans:Q3);
  unknown cost counts as $0 with a warning (ans:Q14); conditions read `sf.budget.remaining()`.
  The owner renamed the wrapper from `sf.Budget` to `sf.WithBudget` on 2026-10-26, because
  `sf.Budget` had the same name as the E4a record `sf.budget.Budget`.
- **Report:** a "Branches" section per Gate and a run summary with the share resolved at the
  first branch, calls avoided, refusals, `fail_closed` and abstain counts.

No url4 grammar change. New Engine endpoints, one new evidence record (`gate-decision.v1`), three
new failure codes (`fail_closed`, `quorum_not_met`, `signal_missing`), one new abstain reason
(`budget_refused`), additive report.v1 and combine-evidence.v1 keys.

**Path prefixes.** `E/` = `apps/screamingface-engine/src/screamingface_engine/`, `S/` =
`packages/screamingface/src/screamingface/`, `U/` = `packages/url4/src/url4/`, `ET/` =
`apps/screamingface-engine/tests/unit/`, `ST/` = `packages/screamingface/tests/`. Line numbers
are on `e4b-integrated`.

## 2. Epic map (OME-1291)

| Epic item | Where |
|---|---|
| 1. Choose one branch before anyone answers; required default; unknown label → default, marked; branch = model, Fusion or Pipeline; report shows input summary, label, zero-call branches | [gate](prd/gate.md), [selectors](prd/selectors.md), [report](prd/report.md) |
| 1. RegexClassifier / Model selectors | [selectors](prd/selectors.md) |
| 1. Clusters selector | deferred (ans:Q4) |
| 1. Subset / topology papers (k of N) | [skip-members](prd/skip-members.md) (ans:Q16) |
| 2. Cheap first, escalate on a declared comparison; original question; report every tier | [cascade](prd/cascade.md), [branch-core](prd/branch-core.md) |
| 2. Human as last tier (abstain, counted as declined) | [cascade](prd/cascade.md) (`sf.abstain()` as the last part), [report](prd/report.md) |
| 3. Budget the decision can see; refuse the call that would pass the cap; report spend vs cap | [budget](prd/budget.md) |
| 4. Guards: ordered, data conditions, `fail_closed` / floor, label still recorded | [guards](prd/guards.md) |
| E4b DB-5: "E4c makes the fallback call not run" | [lazy-fallback](prd/lazy-fallback.md) |
| Open question: USD vs tokens | both, unit named in the recipe (ans:Q3) |
| Open question: set-valued Router vs Cascade | one mechanism; skip-Gate members (ans:Q16) |
| Open question: `fail_closed` vs abstain | separate: failure code vs scored decline ([guards](prd/guards.md)) |
| Non-goals: counting/merging, defining signals, debate, token-level exit, GAIA/browsers/SQL, training routers | out ([docs](prd/docs.md) "Not this epic") |

Child tickets (ans:Q5): OME-1465 sequential first-success → [cascade](prd/cascade.md)
(`sf.escalate_if(sf.unanswered())`); its parallel race form is out (OME-559). OME-1350 → Gate + Cascade. OME-1357
→ the routing / cascade / orchestration definitions in [docs](prd/docs.md). OME-1356 → spend vs
cap only ([budget](prd/budget.md), [report](prd/report.md)); multi-account and local hardware are
E13. OME-1427 → composition only; typed I/O shells are a separate leaf. OME-1630 → Cascade over
sample panels, no reuse; incremental top-up stays a follow-up. OME-1470 → out of E4c.

## 3. Subsystems and ownership

| Subsystem | Owns | Changed by |
|---|---|---|
| url4 package (`U/`) | grammar, executor, `iterate`, typed budget annotation | nothing (no grammar change) |
| Engine branch runtime (`E/world/branch.py`, new) | DECIDE, OPEN, JOIN, KEYWORDS endpoints | branch-core, selectors, budget, guards |
| Engine combine (`E/combine/`) | panel decision (E4b gate), `phase=decide`, `selection`/`skipped` | lazy-fallback, gate, skip-members |
| Engine contract and vocabularies | `OperationOutput.decision`, `fail_closed`, `budget_refused`, attribution pattern, `BudgetStage` | branch-core, guards, budget |
| SDK surface (`S/_surface/`) | `sf.Gate`, `sf.Cascade`, selectors, `sf.WithBudget`, `sf.Estimate` | gate, cascade, selectors, skip-members, budget |
| SDK compiler (`S/_evaluation/`) | the gated url4 shape, rebuild | branch-core, gate, lazy-fallback |
| SDK report (`S/_ui/`, `S/report.py`) | decode, Branches section, run summary, export | report |
| Docs | README section, recipes, notebook 20, CHANGELOG | docs |

## 4. Doc index and reading order

1. [erd.md](erd.md) — the records.
2. [prd/branch-core.md](prd/branch-core.md) — the shared runtime (component).
3. [prd/selectors.md](prd/selectors.md) — the selector values (component, PR-1).
4. [prd/gate.md](prd/gate.md) → [prd/lazy-fallback.md](prd/lazy-fallback.md) →
   [prd/cascade.md](prd/cascade.md) — PR-1 flows.
5. [prd/guards.md](prd/guards.md) → [prd/skip-members.md](prd/skip-members.md) — PR-2 flows.
6. [prd/budget.md](prd/budget.md) → [prd/docs.md](prd/docs.md) — PR-3 flows.
7. [prd/report.md](prd/report.md) — display for every flow.
8. [contracts.md](contracts.md), [test-plan.md](test-plan.md).
Plan: [docs/plan/2026-10-22-e4c-routers-cascades.md](../../plan/2026-10-22-e4c-routers-cascades.md).

## 5. Interview ledger

| Q | Question (short) | Answer |
|---|---|---|
| Q1 | Mechanism for zero calls | Gated iterate (CorrectiveLoop shape), no grammar change |
| Q2 | Base | New worktree with the E4b PRs merged on main |
| Q3 | Budget units and "would exceed" | USD and tokens; spend so far + author-declared estimate |
| Q4 | Clusters selector | Deferred |
| Q5 | Child-ticket scope | As triaged (OME-1465 sequential in, race out; OME-1350/1357 in; OME-1356 spend vs cap; OME-1427 composition; OME-1630 via Cascade; OME-1470 out) |
| Q6 | Widen `sf.Gate` | Option C: Gate is the general branch construct |
| Q7 | Adaptive sampling | Option A: Cascade over sample panels, no reuse, documented |
| Q8 | v1 scope beyond the core | RegexClassifier + Model selectors, set-valued, guards, budget (all four) |
| Q9 | N-way shape | Only `sf.Gate` (against the recommendation of a separate `sf.Route`) |
| Q10 | Where Gate / Cascade may appear | Root, Pipeline stage, branch; not a Fanout member |
| Q11 | Delivery | 2–3 grouped PRs |
| Q12 | N-way form | Strict nested binary Gates (against the recommendation of a `cases=` form) |
| Q13 | Budget scope | Per Case only |
| Q14 | Unknown cost under a USD cap | Count as $0, warn (against the recommendation to refuse further optional calls) |
| Q15 | Guard conditions | Regex on the question, classifier label |
| Q16 | Set-valued with strict binary | Skip-Gate as a Fanout member (the one exception to Q10) |
| Q17 | Failed / abstained cascade stage | SUPERSEDED 2026-11-12 by §5.1 R2. (Was: escalate to the next stage.) |
| Q18 | Guard vs selector label | No model call after a fired guard; a model selector shows "not run" |
| Q19 | Where the cap is written | Once, on the candidate |
| Q20 | Parallel optional calls that jointly pass the cap | Accept the overspend; the report shows it (against the recommendation to reserve estimates in declared order) |
| Q21 | A replay finds a priced call unpriced | SUPERSEDED 2026-10-27 by Q21b. (Was: replay recomputes the budget and the report flags a differing budget view.) |
| Q21b | One price source live and on replay | A replay always takes the same branch. The budget reads one price record (the final successful attempt) live, on a cache hit and on a pinned-cache replay; no differing-view flag |
| Q32 | The overspend line on a replay | A replay uses the cost of the original run: the line adds what the Budget charged each call (a cache hit: its `cache.reference` cost), which the Engine writes as `charges` on each operation (2026-11-10; owner chose "charge per operation" over a Case-level total) |
| Q22 | "Model calls avoided" with nested Gates | A min–max range over the paths through the skipped body |
| Q23 | A selected skip-Gate member fails under `quorum="all"` | The Case fails with the member's own failure code |
| Q24 | A gated Cascade stage where some members fail | SUPERSEDED 2026-11-12 by §5.1 R2. (Was: decide on the members that answered; only "no member answered" escalates by itself.) |
| Q25 | A panel Gate with a recipe `then=` hits the band or has no votes | Abstain (`in_band` / `no_votes`); neither body runs |
| Q26 | A Gate inside a CorrectiveLoop, or a CorrectiveLoop as a Gate branch | Refused at compile time in v1 |

### 5.1 Owner decisions 2026-11-12 (after Irina's product review)

The code already follows these. Each is tagged `[stated owner 2026-11-12]` in the PRDs.

| # | Decision | Supersedes | PRD |
|---|---|---|---|
| R1 | Line form: `sf.Cascade(t1, sf.escalate_if(c1), t2, sf.escalate_if(c2), t3)`; tiers are positional arguments, each escalation is its own line, the optional last part is `sf.abstain()` or `sf.fail()` after a line. The list form, `escalate_if=` and `otherwise=` are removed, with no alias (unreleased) | the list form; P4, P5 | cascade CA-1, CA-5, CA-9, CA-12, CA-16, CA-18 |
| R2 | Nothing escalates unless a line says so. A tier with a condition line keeps its `sf.Fanout` as written: a member failure fails as its quorum says, an abstain makes the Case abstain, a missing number fails it with the new code `signal_missing`. Only `sf.escalate_if(sf.unanswered())` escalates on no answer. The rule lives in the Engine's Gate, so it holds for every `sf.Gate` with a recipe `otherwise` | ans:Q17, ans:Q24; P16, P20, P31 | cascade CA-6, CA-7, CA-10, CA-29, CA-31; gate GT-28, GT-29; branch-core D4, D4a |
| R3 | Typed outcomes `sf.abstain()` and `sf.fail()` in `then=`/`otherwise=` and as the last Cascade part; the SDK stores the words, so bytes, records and codes do not change; the string `"fail_closed"` is refused, the string `"abstain"` still works (E4b, released in v0.1.12) | the public words | gate GT-4, GT-12, GT-30; guards |
| R4 | Renames: `sf.Keywords` → `sf.RegexClassifier`, `sf.LabelModel` → `sf.LLMClassifier`, `sf.Budgeted` → `sf.WithBudget` with `budget_usd=` / `max_tokens=` (`budget_usd`, not `max_usd`: the cap is not a hard maximum, Q20; owner 2026-11-12); `sf.Estimate` keeps `usd=` / `tokens=`; wire names (`keywords.v1`, `label-model.v1`, kinds `keywords` / `label_model`) stay | the old names | selectors, budget, guards |
| R5 | A condition names the number it reads: `sf.signal("lp").chosen() < 0.7` or `.mean()`. A bare `sf.signal("lp") < 0.7` in a condition raises `TypeError`, because a bare comparison is the per-member test of `sf.Filter` (one expression, one meaning; review round 2 of 2026-11-12 reverses the first reading of the same day) | — | cascade CA-32; gate delta 1 |

Open from the same review: "escalate on failure OR on a low score" has no spelling yet
([cascade](prd/cascade.md) §6).

## 6. Decisions made while writing the spec (owner review)

These are `[proposed]` in the PRDs. Each changes behavior a reader would notice. The owner
approved all of them as written on 2026-10-22. P15–P21 were made explicit after review round 1.

| # | Decision | PRD |
|---|---|---|
| P1 | A recipe branch answers the Gate's input: the Case input at the root and in the first stage; the previous stage's answer in a later Pipeline stage; Cascade tiers answer the Cascade's input | branch-core BC-5, gate GT-8 |
| P2 | The E4b GA-6 limit is lifted: a gated vote may read an extractor (`over=` not a rule name). This reverses E4b decision O14 (refuse) | gate |
| P3 | A gate may sit on any reducer: `agreement` needs a Vote, `chosen:` a reducer that picks a member; else an implicit decision-only Vote | gate |
| P4 | No outcome part by default: the last tier's answer is final; `sf.abstain()` (or `sf.fail()`) after a line makes the last tier gated too (line form since 2026-11-12, R1; was `otherwise=None` / `"abstain"`) | cascade |
| P5 | `sf.escalate_if(sf.unanswered())` = first-success (escalate only on failure / abstain) via a new panel condition `sf.answered()` (line form since 2026-11-12, R1; was `escalate_if=None`) | cascade |
| P6 | `CascadeSeedWarning` when sample panels repeat seeds (cache hits would break "no reuse") | cascade |
| P7 | A failed LLMClassifier call takes the default branch (not a Case failure); DECIDE detects it by the literal `$selector_N` text (the call's code is only in the activity view); `sf.label(sel) != "x"` holds for a null label, so a guard can fail closed on it | selectors, guards |
| P8 | Selector input summary = input length + first 16 hex of its SHA-256; never input text | selectors |
| P9 | Skip members: under `quorum="all"` the member slots are required, so a failed selected member fails the panel with its own code (ans:Q23); an unselected member's JOIN returns `""` and the combine excludes it through `selection`; under a numeric quorum the slots are optional, the url4 panel quorum is 0 and the combine checks the floor over the selected members (`quorum_not_met`); nothing selected → abstain `no_votes` | skip-members |
| P10 | The E4b fallback stays lazy through a combine param `phase=decide` (two-call shape); E4b-era url4s still run | lazy-fallback |
| P11 | Budget: refusal when spent + estimate > cap (equal is allowed); no estimate → refuse only when spent ≥ cap; a refused branch falls back to a no-call branch, else abstain `budget_refused`; calls that always run are never refused | budget |
| P12 | The candidate carries `;budget_mode=advisory` with the cap (mandatory calls may pass it) | budget |
| P13 | `fail_closed` earns no refusal credit on refusal-rate benchmarks (it is an error, as the epic says) | guards |
| P14 | The attribution pattern widens to `gate_N` and `selector_N` (`E/benchmarks/operation_outputs.py:52`, `S/_operation_bindings.py:5-9`); selector calls are accounted as `synthesis` and charged to a new `BudgetStage` `selector` | branch-core, selectors, budget |
| P15 | Branch bodies run inline (not through the corrective `MEMBER_ROUTE`), so their calls reach the Case recorder; JOIN returns plain text, and a refusal inside a body behaves as in a Pipeline stage | branch-core D1, D2 |
| P16 | SUPERSEDED 2026-11-12 by R2: only an `sf.escalate_if(sf.unanswered())` tier compiles with optional members and url4 `quorum=0`, and only it refuses a numeric quorum; a tier with a condition line keeps its Fanout as written. (Was: every gated stage, ans:Q24.) | cascade CA-6, CA-10, CA-17, CA-29 |
| P17 | A selector always reads the Case input, also in a later Pipeline stage | guards GU-19, selectors |
| P18 | A branch is refused when either declared unit refuses it | budget BU-2 |
| P19 | Gate nesting depth is capped at 8 | branch-core BC-18 |
| P20 | Panel branch rule: a null panel branch (no voters) takes `otherwise` only when `otherwise` is a recipe and the condition is `sf.answered()` (R2, 2026-11-12; was: any condition); otherwise, and on a band hit, no branch runs and the decision call's abstain stands, also with a recipe `then` (ans:Q25); JOIN copies the decision call's combine result on a step slot and on no branch, so an E4b abstain still marks the Case | branch-core D4, D12 |
| P21 | The per-Case cap applies per Attempt: each Attempt starts with the full cap | budget BU-28 |
| P22 | Each Gate has a pure AFTER source with instrumental (`0.0`) slots that reference the decision call, the Gate input and the selectors DECIDE reads, so DECIDE runs after them (and, transitively, after every ancestor) with no answer bytes packed; the renderer asserts every AFTER reference resolves in scope | branch-core D10 |
| P23 | DECIDE carries the param `gate=gate_N` and reads the decision call's gate record from the recorded calls (`OperationCall.gate_record` for a pending outcome); nothing is kept in request scope | branch-core D11 |
| P24 | The tree's KEYWORDS source runs in every Gate tree that reads a selector and returns the Case input summary, so LLMClassifier records get it too | branch-core D6, selectors SL-27 |
| P25 | Attribution walks only Gate blocks (`gate_N_block`) and their iterate bodies; the corrective `loop_candidate` stays opaque | branch-core D3 |
| P26 | A Gate inside a CorrectiveLoop, or a CorrectiveLoop as a Gate branch, is refused (ans:Q26) | gate GT-27 |
| P27 | GATE_SPEC carries `terminal` (each recipe body's terminal binding); JOIN copies the recorded result of the branch that ran, so an abstain inside nested bodies (a Cascade's last tier, a body ending in an abstaining Vote, lazy-fallback call #2) reaches the root and marks the Case abstained | branch-core D12, BC-36, BC-37 |
| P28 | A Fanout with skip-Gate members refuses a block `sf.Judge`, Gate model fallbacks (`JudgePick`, `Synthesize`) and other model signal calls in v1, because those calls read the raw panel with empty rows for skipped members | skip-members SM-15 |
| P29 | `sf.Consistency` with skip-Gate members is refused in v1 (the sample panel inside a gated body is not visible to the combine call) | skip-members SM-16 |
| P30 | `quorum_not_met` becomes a declared, permanent failure code (PR-2), so E4c adds two codes: `fail_closed` (PR-1) and `quorum_not_met` (PR-2); the declared count goes 66 → 67 → 68. The owner review of 2026-11-12 (R2) adds a third code, `signal_missing`: 68 → 69 | skip-members SM-11, guards #4, branch-core D4a |
| P31 | A gated last tier after an `sf.escalate_if(sf.unanswered())` line whose members all fail follows its outcome: `sf.abstain()` → abstain `no_votes`; `sf.fail()` → the Case fails with `fail_closed`. After a condition line the CA-6 / CA-7 / CA-31 rules apply (R2, 2026-11-12) | cascade CA-30, branch-core D4 |
| P32 | A Fanout with a skip-Gate member always takes the panel compile path, also under `quorum="all"` | skip-members, contracts C1 |

## 7. Questions for others (not the owner)

- **url4 owner (Kevin):** (a) heads-up that E4c emits gated `iterate` shapes and typed budget
  annotations, with no grammar change; (b) Part E §24 (budget scoping, `budget_mode`) is not in the
  repo: does `;budget_mode=advisory` plus "never send an optional call that would pass the cap"
  conform? Default until answered: as specified in [budget](prd/budget.md). The owner chose to build
  with this default (2026-10-22).

## 8. Global assumptions

- The E4b stack merges as reviewed; E4c rebases onto main after it (the E4a → E4b precedent).
- Release order: the Engine ships before the SDK [stated owner 2026-11-12, review round 2 (S1) —
  supersedes "SDK first"]. WHY: the Engine writes the new words and keys (`charges`, the Gate and
  budget records, `fail_closed`, `signal_missing`, `budget_refused`) only for a recipe that uses an
  E4c branch, and an older SDK cannot build one, so an older SDK is safe on the new Engine (the
  OME-1233 decoder rule holds). A new SDK on an older Engine pays every member and then fails each
  Case on `phase=decide`. An SDK check before the first paid call needs an Engine capability
  signal that does not exist yet (follow-ups `OME-1921` Engine signal, `OME-1922` SDK refusal).
- No live or paid run is needed to build or review E4c (offline fake gateway, recorded replies).

## 9. Delivery (ans:Q11)

| PR | Content |
|---|---|
| PR-1 branch core | branch-core (incl. attribution), selectors, gate, lazy-fallback, cascade, the `fail_closed` vocabulary, report (decode, Gate sections, summary), CHANGELOG |
| PR-2 selection | guards, skip-members, report (skip lines), CHANGELOG |
| PR-3 budget and docs | budget (with the budget rows of guards and skip-members), report (budget lines), docs (README section, recipes, notebook 20), CHANGELOG |

Input gates need a selector to read, so the selectors are in PR-1; the `fail_closed` code is in
PR-1 because the Gate word exists from PR-1 (plan §1).
