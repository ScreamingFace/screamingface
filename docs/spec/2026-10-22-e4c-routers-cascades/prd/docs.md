# PRD: Docs — README, CHANGELOG, notebook 20, docstrings

**Source:** epic OME-1291, OME-1357 (routing vs orchestration definitions), ans:Q4, ans:Q5,
ans:Q7, ans:Q9, ans:Q12, ans:Q16–Q19 · **Priority:** P2 (ships with PR-3, the last PR, ans:Q11)
**Lifecycle:** existing (characterize + delta): the README, the CHANGELOG, the notebooks and some
docstrings describe the E4b "fallback runs on every Case" state · **Owner:** unassigned
Paths: [erd §1–§6](../erd.md) · contracts: C9 (offline recipe fixtures) · uses: every flow PRD
([gate](gate.md), [lazy-fallback](lazy-fallback.md), [cascade](cascade.md),
[selectors](selectors.md), [skip-members](skip-members.md), [guards](guards.md),
[budget](budget.md), [report](report.md))

## 1. Summary and user story

As a researcher who wants to reproduce a router or cascade paper, I want the SDK README to tell
me in one section what "routing", "cascade" and "orchestration" mean in this toolkit, and to give
me one recipe per paper family that I can copy, so that I can write the method without reading
the Engine code. I want each recipe to be the code that the Engine proves offline, and the
CHANGELOG to tell me what changed in E4b recipes that I already have.

## 2. Background and constraints

- "Define first-class routing vs orchestration primitives … think about how to actually form a
  nice definition of how these two are" (OME-1357, Evan Chen). [stated epic — child scope ans:Q5]
- E4c ships ONLY `sf.Gate` as the branch construct, with no `sf.Route` class. [stated ans:Q9]
  N-way routing is strict nested binary Gates on `sf.label(sel) == "x"`. [stated ans:Q12]
- Adaptive sampling is a Cascade over sample panels, with no sample reuse, and the docs say so.
  [stated ans:Q7]
- Clusters is deferred [stated ans:Q4]; the parallel race of OME-1465 is out [stated ans:Q5].
- Set-valued routing is a skip-Gate Fanout member [stated ans:Q16]; a failed stage escalates
  [stated ans:Q17]; a fired guard makes no model call [stated ans:Q18]; the budget is written once
  on the candidate [stated ans:Q19]; an unknown cost counts as $0 with a warning [stated ans:Q14].
- Docs tests run recipe code OFFLINE only: they build the recipe and compile it to url4 bytes. They
  never call a model, a gateway, or a hosted service. A docs reviewer once ran README blocks after
  "Install" and that started live Cloudflare Access logins (2026-10-21 incident). [proposed — owner
  standing rule "no network, recipe blocks only"]
- "Not this epic" list of the epic: counting/copying/merging (E4a), defining confidence/embeddings
  (E4b), debate (E4d), early exit inside a token loop, tool/agent benchmarks (E10c/E10d/E10e),
  training the router. [stated epic]

### 2.1 Current behavior

- README `### Gate the majority` (`packages/screamingface/README.md:1078-1147`) says: "In this
  version the fallback call runs on every Case, also when the gate keeps the majority, and you pay
  for it. The gate chooses and records; a cascade that skips the call comes with E4c."
  (`:1097-1099`) [existing]. `test_gate_docs.py:50-52` pins this sentence [existing].
- README `### Signal sources`, recipe S16 (`:1074-1076`): "The larger model still runs on every
  Case: a cascade that skips it comes with E4c." `test_signal_recipes_readme.py:37-38` pins the
  tokens "larger model still runs" and "E4c" [existing].
- README `### Sum signals and the abstain band` (`:1206`): "A judge or writer fallback still runs
  on every Case, also when the number is in the band; its reply is not read."
  `test_sum_band_docs.py:76-79` pins it [existing].
- README `## Examples` (`:1804-1830`) lists notebooks up to `18_map_select_reduce.ipynb`; "All
  notebooks are deterministic outputs of `scripts/build_notebooks.py`" [existing].
- Notebook pattern: `scripts/build_notebooks.py:67` maps `"18_map_select_reduce.ipynb":
  _map_select_reduce()` (`:2211`); `scripts/check_notebooks.py` verifies every notebook equals
  its builder output [existing]; `ST/test_example_18_recipes.py` runs the code cells and compiles
  each recipe with the flow operator catalog, with the evaluation cell off by default [existing].
- README-recipe pattern: `ST/test_combine_recipes_readme.py` and `ST/test_gate_docs.py` run the
  README section's code block and compile each assigned recipe; the url4 must be byte-equal to the
  fixture that the Engine runs (`ST/test_gate_docs.py:43-46`, `:140-142`) [existing].
- Docstrings and messages that name E4c as future work: `S/_surface/gate.py:37`, `:45` ("E4c will
  skip it when the gate passes"), `:88` ("sf.Gate then= takes sf.Vote until E4c"), `:91`;
  `S/gate.py:8` ("E4c (OME-1291) removes the unused call"); `S/_signals.py:56`; `S/budget.py:3`,
  `:6`, `:156`; `E/budget.py:3`, `:84`; `E/combine/ports.py:55`; `E/combine/endpoint.py:882`
  [existing].
- No README section, recipe, notebook or CHANGELOG entry for routing or cascades [existing].

Delta: one new README section, three rewritten README sentences (each pinned by an existing test,
so three owner-approved pinned edits), CHANGELOG Unreleased entries, notebook 20, the Examples
list, and the docstrings above rewritten to the shipped behavior.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DC-1 Definitions.** Given the README, When a reader opens `### Choose whether a model runs`
  (a new `###` section after `### Consistency samples`, before `## Install`), Then its first
  paragraph defines: **routing** = a `sf.Gate` that decides BEFORE any answer exists, from the
  question (a selector label) or the budget; **cascade** = a `sf.Gate` that decides AFTER an answer,
  from a number on that answer (agreement or a declared signal), and calls the next stage on the
  original question; **orchestration** = multi-step controllers, debate and agent loops, which are
  not in this toolkit yet (E4d, E10c). It states the one rule: a branch that is not selected makes
  zero model calls, and the report says it was not selected and why. [stated epic; stated ans:Q5 —
  OME-1357]
- **DC-2 One construct.** Given the section, Then it says that `sf.Gate` is the only branch
  construct: `then=` and `otherwise=` take a reducer step, a recipe, `"abstain"` or
  `"fail_closed"`; an N-way choice is nested Gates; `sf.Cascade` is a short form of nested Gates
  whose `repr` shows the Gate form. [stated ans:Q6, ans:Q9, ans:Q12]
- **DC-3 Recipe per paper family.** Given the section's one Python code block, Then it assigns
  these recipes, each with a one-line comment that names the paper family [stated epic paper lists]:

  | Recipe | Family (epic) | Shape |
  |---|---|---|
  | `d1_keyword_router` | Keywords router; "How robust are router-LLMs?" binary router | `sf.Gate(when=sf.label(kw) == "math", then=math_panel, otherwise=sf.Gate(when=sf.label(kw) == "code", then=coder, otherwise=general))` |
  | `d2_label_router` | GraphRouter / OrgAgent (DIRECT, LIGHT, FULL) / single- vs multi-agent | nested Gates on `sf.label(sf.LabelModel(m, labels=[...]))` |
  | `d3_guarded_router` | router robustness (`fail_closed`), floor | outer Gate on a Keywords label → `then="fail_closed"`; a classifier label → `then=<stronger recipe>`; `otherwise=d2` |
  | `d4_cope_cascade` | COPE, Frugal KG, CARGO | `sf.Cascade([panel >> sf.Vote(), large], escalate_if=sf.agreement() < 0.8)` |
  | `d5_steer_answer_cascade` | STEER (per full answer) | `sf.Cascade([sf.Fanout([small], signals={"lp": sf.Logprob("prob")}) >> sf.Vote(), large], escalate_if=sf.signal("lp").chosen() < 0.7)` (a gated stage is a block that ends in a reducer, [cascade](cascade.md) CA-13) |
  | `d6_first_success` | OME-1465 first branch to succeed | `sf.Cascade([a, b, c])` with failure escalation, no condition beyond "answered" |
  | `d7_manager_subset` | Team of Thoughts, SMART-D, set-valued routing | `sf.Fanout([sf.Gate(when=sf.labels(sel).has("x"), then=agent_x), …]) >> sf.Synthesize(writer)` |
  | `d8_budget_choice` | OmniRouter, RouterBench willingness-to-pay | `sf.Gate(when=sf.budget.remaining() >= 0.02, then=large, otherwise=small)` |
  | `d9_budget_cap` | MTRouter / VineLM cap | `sf.Budget(d4_cope_cascade, usd=0.05)` |
  | `d10_adaptive_sampling` | ACAR, OME-1630 | `sf.Cascade([sf.Fanout(sf.samples(m, 2)) >> sf.Vote(), sf.Fanout(sf.samples(m, 5, seeds=range(2, 7))) >> sf.Vote()], escalate_if=sf.agreement() < 1.0)` (fresh seeds, so no `CascadeSeedWarning`, [cascade](cascade.md) CA-11, CA-23) |

  Exact argument names follow the flow PRDs; this table fixes only the recipe names and shapes.
  [proposed]
- **DC-4 Recipes are the proven code.** Given each recipe, When the docs test compiles the code
  block offline (`compile_candidate`, the flow or Engine operator catalog), Then each url4 is
  byte-equal to the fixture that the Engine runs offline (contract C9). [existing pattern
  `ST/test_gate_docs.py:140-142`; proposed rows]
- **DC-5 What it costs, now true.** Given the section and the rewritten `### Gate the majority`
  paragraph, Then they say that a branch that is not taken makes no call and costs nothing, that
  the E4b gate fallback runs only on the Cases where the gate takes it, and that the band branch
  reads no reply and runs no fallback. [stated epic; implied — lazy-fallback PRD]
- **DC-6 Outcomes.** Given the section, Then it says: `"abstain"` (and the last tier of a Cascade)
  is a scored decline with reason `gate_not_met`; a budget refusal with no free branch abstains
  with `budget_refused`; `"fail_closed"` is a failure with code `fail_closed`, never an abstain.
  [stated epic: "Abstain is a scored decline. Fail-closed is an error."; proposed reasons, erd §6]
- **DC-7 Limits that the docs must state.** Given the section, Then it states, each in one
  sentence: (a) adaptive sampling does not reuse the first stage's samples, so an escalated Case
  pays for 2 + 5 samples, not 2 + 3 (OME-1630 tracks the top-up) [stated ans:Q7]; (b) STEER's
  step-level, per-token escalation is not done, only per full answer [stated epic non-goal];
  (c) a fired guard runs no model, so a model selector after it shows "not run" [stated ans:Q18];
  (d) a call with unknown cost counts as $0 against a USD cap and the report warns
  [stated ans:Q14]; (e) the budget is per Case and written once, on the candidate
  [stated ans:Q13, ans:Q19]; (f) a failed or abstained stage escalates; only the last stage's
  failure fails the Case [stated ans:Q17].
- **DC-8 Not this epic.** Given the section, Then it ends with a "Not in E4c" list: Clusters
  (embedding) routers [stated ans:Q4]; the parallel first-success race that cancels slower branches
  [stated ans:Q5]; counting/merging (E4a), measuring confidence (E4b), debate (E4d), token-level
  early exit, tool and agent benchmarks (E10c/E10d/E10e), training a router [stated epic].
- **DC-9 CHANGELOG.** Given `packages/screamingface/CHANGELOG.md` `## Unreleased`, Then:
  `### Breaking changes` has (1) `sf.Gate` takes a step, a recipe, `"abstain"` or `"fail_closed"`
  in `then=`/`otherwise=`; the E4b "until E4c" limits (`then=` must be a Vote; a gated vote reads a
  rule name) are gone; (2) the E4b gate fallback now runs only when the gate takes it, so cost and
  operation lists change for gated recipes. `### Features` has one bullet each for nested-Gate
  routing with `sf.Keywords` / `sf.LabelModel`, `sf.Cascade`, skip-Gate Fanout members, guards and
  `fail_closed`, `sf.Budget` + `sf.budget.remaining()`, and the report "Branches" section. One
  bullet names the new failure code `fail_closed` and the abstain reason `budget_refused`, and says
  that the SDK release with both words ships before the Engine (OME-1233). E4c bullets go first in
  their sections (E4b precedent: commit `ea90188c1`). [proposed — gap §per-connection/dependency]
- **DC-10 Notebook 20.** Given `scripts/build_notebooks.py`, Then it builds
  `examples/20_routers_cascades.ipynb` from a new `_routers_cascades()` builder, registered in the
  notebook map beside `18_map_select_reduce.ipynb` (`:67`): every DC-3 recipe in its own cell with
  `repr` and the compiled url4, a cell that shows the Gate form behind one `sf.Cascade`, and one
  evaluation cell that is off by default (`RUN_EVALUATION = False`). The README `## Examples` list
  gets one line for it. [proposed — exemplar notebook 18]
- **DC-11 Docstrings.** Given every docstring and message listed in §2.1, Then none says E4c is
  future work: they describe the shipped skip, or they are removed with the limit they explained.
  [proposed]

### 3.2 Error paths

- **DC-12 A recipe block that would reach the network.** Given the docs test runs a README or
  notebook code block, When the block names `sf.Client(`, `sf.evaluate(`, `.connect(`, a hosted
  URL or a login helper, Then the test fails before it executes the block, and names the marker.
  [proposed — owner standing rule; gap §security]
- **DC-13 Stale url4 bytes.** Given a flow PRD changes the compiled shape of a Gate, When the docs
  test compiles the README block, Then it fails with the recipe name and the first differing byte
  offset against the Engine fixture, so README and fixture move together. [proposed]
- **DC-14 Notebook drift.** Given a hand edit to `20_routers_cascades.ipynb`, When
  `scripts/check_notebooks.py` runs, Then it fails because the file differs from the builder
  output. [existing `scripts/check_notebooks.py`]

### 3.3 Derived scenarios (risk-ordered)

| # | Title | Tag | I×L | G/W/T |
|---|---|---|---|---|
| DC-15 | Pinned README sentences change with approval | [implied] | H×H | Given the three sentences of §2.1, When they are rewritten, Then `test_gate_docs.py:50-52`, `test_signal_recipes_readme.py:38` and `test_sum_band_docs.py:76-79` change only through owner-approved pinned edits (manifest under `.claude/test-change-approvals/`), and the new text keeps every other pinned token ("larger model still runs" stays, now followed by "write it as a `sf.Cascade` to skip it"). |
| DC-16 | Notebook evaluation cell stays off | [proposed — gap §security] | H×M | Given notebook 20, When the offline test runs its code cells, Then no cell makes a request; the evaluation cell is guarded by `RUN_EVALUATION = False`. |
| DC-17 | Every recipe in the README is compiled | [proposed] | M×M | Given the section's code block, Then the set of assigned `d*` names equals the DC-3 table; a new recipe without a fixture, or a fixture without a recipe, fails the test. |
| DC-18 | Section reads in STE and has no forward reference | [proposed] | M×M | Given the section, Then it does not contain "E4c", "will", "comes with" or "later" about skipping; it uses the words of the report ("Branches", `not_selected`, `budget_refused`). |
| DC-19 | Definitions match the code | [proposed] | M×M | Given the DC-1 definitions, Then each term appears in `S/_surface/gate.py`'s class docstring with the same meaning (routing = input gate, cascade = panel gate). |
| DC-20 | Paper names stay links-free claims | [proposed] | L×M | Given the recipe comments, Then each names a paper family without a claim that the recipe reproduces the paper's numbers; the section says the recipes reproduce the decision shape only. |
| DC-21 | Examples list and builder agree | [existing `scripts/check_notebooks.py`] | L×M | Given the README `## Examples` list, Then every listed notebook file exists and is in the builder map. |

## 4. Non-functional requirements

- Docs tests are offline and fast: the README and notebook-19 tests together run in < 10 s on the
  SDK test host, with no network socket opened (`pytest-socket` style guard or a marker scan)
  [proposed].
- STE for all README prose; code, url4 and quoted words stay verbatim [proposed — owner writing
  standard (STE)].
- The README section stays ≤ 220 lines; long explanations link to the report section
  `### Combine steps in the report` instead of repeating it [proposed].

## 5. Out of scope

- public-docs site pages (`public-docs/src/pages/learn/*.vue`): no recipe page exists there today;
  a public "routing" page is a follow-up [proposed].
- Docs for Clusters routers [stated ans:Q4] and the parallel race [stated ans:Q5].
- Paid or live notebook runs [proposed — owner standing rule "no full evals"].

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in on the reader's path: pinned characterization first, then the guard that keeps
docs tests offline (highest risk: a live login), then recipe bytes, then prose, then notebook.
New test files: `ST/test_routers_cascades_docs.py` (README section + CHANGELOG),
`ST/test_example_20_recipes.py` (notebook cells). RED first, always.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `gate_section_states_the_e4b_fallback_cost` (today's `test_gate_docs.py` pins pass) | unit | [existing `ST/test_gate_docs.py:50-52`] | H×M | passes today |
| 2 | `docs_blocks_with_network_markers_are_refused_before_exec` (README section + notebook 20 cells scanned for `sf.Client(`, `sf.evaluate(`, `.connect(`, `login`, `https://`) | unit | DC-12 | H×H | marker scan before `exec`; reuse the `_STORY_MARKERS` idea of `scripts/check_notebooks.py` |
| 3 | `readme_router_recipes_compile_to_the_engine_fixtures` (parametrized over the DC-3 names) | unit | DC-3, DC-4 | H×H | README code block; fixtures from contract C9 |
| 4 | `stale_recipe_bytes_name_the_recipe_and_offset` | unit | DC-13 | H×M | custom assertion message |
| 5 | PIN `gate_section_says_the_fallback_runs_only_when_taken` (owner-approved edit of `test_gate_docs.py:50-52`) | unit | DC-5, DC-15 | H×H | rewrite README `:1097-1099` |
| 6 | PIN `s16_points_to_cascade_to_skip_the_larger_model` (edit of the "E4c" token at `test_signal_recipes_readme.py:38`; "larger model still runs" kept) | unit | DC-15 | H×M | rewrite README `:1074-1076` |
| 7 | PIN `band_section_says_no_fallback_runs_in_the_band` (edit of `test_sum_band_docs.py:76-79`) | unit | DC-5, DC-15 | H×M | rewrite README `:1206` |
| 8 | `section_defines_routing_cascade_orchestration` | unit | DC-1 | M×H | new README section |
| 9 | `section_says_gate_is_the_only_branch_construct` | unit | DC-2 | M×M | — |
| 10 | `section_states_the_outcomes_and_their_codes` (`gate_not_met`, `budget_refused`, `fail_closed`) | unit | DC-6 | H×M | — |
| 11 | `section_states_each_limit` (parametrized over DC-7 a–f) | unit | DC-7 | H×M | — |
| 12 | `section_lists_what_is_not_in_e4c` | unit | DC-8 | M×M | — |
| 13 | `readme_recipe_set_equals_the_table` | unit | DC-17 | M×M | — |
| 14 | `section_has_no_forward_reference_to_skipping` | unit | DC-18 | M×M | — |
| 15 | `changelog_unreleased_has_the_breaking_and_feature_bullets_first` | unit | DC-9 | M×M | reuse `_unreleased`, `_first_features_bullets` (`ST/test_show_signals_docs.py`) |
| 16 | `notebook_20_recipes_build_and_compile_offline` | integration | DC-10, DC-16 | H×M | `_routers_cascades()` builder; exemplar `ST/test_example_18_recipes.py` |
| 17 | `notebook_19_matches_its_builder` | unit | DC-14 | M×M | `scripts/check_notebooks.py` covers it once registered |
| 18 | `examples_list_names_notebook_19` | unit | DC-21 | L×M | README `## Examples` line |
| 19 | `no_docstring_or_message_names_e4c_as_future_work` (grep of `S/` and `E/` src for "E4c will", "until E4c", "E4c removes", "E4c can", "comes with E4c") | unit | DC-11 | M×M | rewrite the §2.1 sites |
| 20 | `definitions_match_the_gate_docstring` | unit | DC-19 | M×L | `S/_surface/gate.py` class docstring |
| 21 | `recipe_comments_claim_the_decision_shape_only` | unit | DC-20 | L×M | — |

Pinned files (owner approval before GREEN): `ST/test_gate_docs.py` (:50-52),
`ST/test_signal_recipes_readme.py` (:38), `ST/test_sum_band_docs.py` (:76-79). Row 19 may also
touch message-text tests for `S/_surface/gate.py:88`/`:91` if those messages survive; the
[gate](gate.md) PRD owns removing those limits and their tests.
