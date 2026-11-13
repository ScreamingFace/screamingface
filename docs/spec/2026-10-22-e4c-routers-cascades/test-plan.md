# Test plan: E4c

Cross-cutting test strategy and the TDD ground rules. The per-feature test lists are in each PRD
§7; this file aggregates them, ranks the risks and lists the pinned edits and what is not tested.

## 1. Ground rules (every unit inherits them)

- **RED first, always.** Write the test, run it, see it fail for the right reason (an assertion on
  the missing behavior, not an import error or a fixture crash). A test that passes at once proves
  nothing: fix the test.
- **GREEN minimally**, then **REFACTOR on green only**.
- **CHAR rows** pin today's behavior and pass on the base by design (`e4b-integrated`, 031780873).
  They run before the delta rows of their PRD.
- **PIN rows** are edits of existing pinned tests or snapshots. They need owner approval through a
  blob-pinned manifest in `.claude/test-change-approvals/` (url4 fixtures under `tests/` included).
  Agents never write that directory.
- **Offline only.** No live provider call, no paid test, no eval run. Engine runs use the
  Engine-world fake gateway that counts calls per binding. Docs tests compile recipe code to url4
  bytes; they never execute a block that reaches the network (the 10-21 incident rule).
- **Gates:** `timeout 1500 uv run --script .claude/scripts/run_gates.py <stack> --base e4b-integrated`,
  one stack at a time (the engine suite hangs under parallel load). The append-only check uses
  `--base e4b-integrated` so it sees only E4c test edits. SDK venv: `uv sync --frozen --extra
  notebook`.

## 2. Levels (test pyramid)

| Level | What | Share |
|---|---|---|
| unit | endpoint decision tables, record models, SDK constructors, lowering, compile bytes, decoders, views | ≈ 70 % |
| integration (Engine world) | a compiled url4 runs on the fake gateway: call counts per binding, Case outcome, attached records, replay | ≈ 25 % |
| docs/offline recipe | README and notebook recipes compile to the C9 fixtures | ≈ 5 % |

No E2E against a live gateway. The "zero calls" guarantee is proven at the integration level with
call counts per binding, because a unit test cannot see a call that url4 did not schedule.

## 3. Risk register (drives the order of every PRD §7)

| ID | Risk | I×L | Covered by |
|---|---|---|---|
| R1 | An unselected branch still makes a call (the epic's core rule broken) | H×H | branch-core #12, gate #19, cascade #2, lazy-fallback #6, skip-members #3, guards #8, selectors #9 |
| R2 | A hidden eager dependency: a body references an outer model source, so it runs on an empty collection | H×H | branch-core #17 |
| R3 | Operations inside gated bodies are not attributed (decision, evidence, accounting lost) | H×H | branch-core #2, #7, #8, #13, #27, #30 |
| R4 | Replay takes a different branch than the live run | H×M | branch-core #21, lazy-fallback #13, budget #9, #24, selectors #13, #23, skip-members #14, report #28 |
| R5 | E4b evidence or url4 bytes change for recipes without a lazy fallback | H×M | gate #1–#3, lazy-fallback #1–#5, #9, #20, report #1–#2 |
| R6 | `fail_closed` and abstain share a status or a score path | H×M | guards #12, #17, branch-core #14, #15, report #6 |
| R7 | A fired guard still pays for a model selector | H×M | guards #9, selectors #9 |
| R8 | Budget overspends silently or refuses a mandatory call | H×M | budget #4–#11, #16; report #19 |
| R9 | A cascade tier escalates when no line says so, or an `sf.escalate_if(sf.unanswered())` tier fails the Case instead of escalating (owner 2026-11-12) | H×M | cascade #4, #5, #5a, #6, #11, #11a, #12; gate #33, #34; branch-core #9a, #9b (a condition-line tier keeps its Fanout quorum; an `sf.unanswered()` tier has url4 `quorum=0`; a gated last tier with no voters follows its outcome) |
| R10 | Record or report leaks prompt, input or answer text | H×M | branch-core #29, selectors #17, guards #18, report #14 |
| R11 | JOIN passes an envelope or swallows a refusal | H×M | branch-core #5, #6, #18, #19 |
| R12 | Docs show a recipe that compiles differently or calls the network | M×M | docs #2–#4, #16, #17 |
| R13 | Vocabulary drift between Engine and SDK (new code, reason, stage) | M×M | guards #3–#7, budget #22, report #32 |
| R14 | Unknown labels, parse failures or failed selector calls do not take the default | M×M | selectors #6–#8, guards #20–#22, report #35 |
| R15 | DECIDE runs before the data it reads (url4 has no edge to the decision call or the ancestors) | H×H | branch-core #10, #17a, #31, #32 |
| R16 | An abstain stops marking the Case once the root names `gate_N` (E4b vote, nested Cascade last tier, recipe body ending in a Vote) | H×H | branch-core #6, #6a, #6b, #11; lazy-fallback #11; cascade #10 |
| R17 | A model call over a skip-member panel reads the empty rows of skipped members, or a sample panel is invisible to the combine | H×M | skip-members #5a, #5b |

## 4. Totals

| PRD | Prefix | Scenarios | TDD rows | PR |
|---|---|---|---|---|
| [branch-core](prd/branch-core.md) | BC | 39 | 45 | PR-1 |
| [selectors](prd/selectors.md) | SL | 27 | 25 | PR-1 |
| [gate](prd/gate.md) | GT | 30 | 35 | PR-1 |
| [lazy-fallback](prd/lazy-fallback.md) | LF | 22 | 24 | PR-1 |
| [cascade](prd/cascade.md) | CA | 32 | 30 | PR-1 |
| [report](prd/report.md) | RP | 35 | 36 | PR-1 (29 rows), PR-2 (1), PR-3 (6) |
| [guards](prd/guards.md) | GU | 21 | 29 | PR-1 (vocabulary, 6 rows), PR-2 (22), PR-3 (1) |
| [skip-members](prd/skip-members.md) | SM | 23 | 29 | PR-2 (28 rows), PR-3 (1) |
| [budget](prd/budget.md) | BU | 28 | 28 | PR-3 |
| [docs](prd/docs.md) | DC | 21 | 21 | PR-3 (each PR updates the CHANGELOG for its part) |
| **Total** | | **278** | **302** | |

## 5. Pinned edits expected (owner approval, per PR manifest)

| PR | File | Why |
|---|---|---|
| PR-1 | the Engine-only `ET/data/combine_contract/binding_names.json` (the SDK conformance test reads it); the pattern in `E/benchmarks/operation_outputs.py:52` and `S/_operation_bindings.py:5-15` (`OPERATION_REFERENCE`, `TOPOLOGY_BINDING` + `gate_\d+_block`); `ST/unit/test_binding_pattern_conformance.py` | attribution admits `gate_N`, `selector_N` (branch-core #26) |
| PR-1 | `ET/test_failure_classes.py`, `ET/test_e4b_catalog_pins.py` (66 → 67), `ET/test_terminal_error_detail.py` | failure code `fail_closed` (guards #3–#5, built in PR-1) |
| PR-1 | `ST/test_gate_surface.py:316-319`, `:375-379`, `:432-437` | E4b "until E4c" limits lifted (gate #7, #8, #28) |
| PR-1 | `ET/test_combine_gate_words.py:397-403` | a gate on any reducer (gate #18) |
| PR-1 | `ET/data/combine_contract/gate_judge_vote_candidate.url4`, `gate_writer_vote_candidate.url4`; `ST/test_gate_api.py` one-call-shape rows | lazy fallback shape (lazy-fallback #23, #24) |
| PR-1/2/3 | `ST/public_surface_snapshot.json` | `Gate` signature (`otherwise=None` sentinel); `Cascade`, `escalate_if`, `unanswered`, `abstain`, `fail`, `CascadeSeedWarning`; `RegexClassifier`, `LLMClassifier`, `label`, `labels`; `Budget`, `Estimate`, `budget` |
| PR-2 | `ET/test_failure_classes.py`, `ET/test_e4b_catalog_pins.py` (67 → 68), `ET/test_terminal_error_detail.py` | failure code `quorum_not_met` (skip-members #2a) |
| owner 2026-11-12 | `ET/test_failure_classes.py`, `ET/test_e4b_catalog_pins.py` (68 → 69), `ET/test_terminal_error_detail.py` | failure code `signal_missing` (branch-core #9b, BC-39, D4a) |
| PR-2 | `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`; likely `ET/test_combine_evidence_words.py`, `ST/test_evidence_words.py`, `ST/test_frozen_record_fields.py` | evidence key `skipped`, NR-I4 (skip-members #25) |
| PR-3 | `budget_schemas()` freeze snapshot; `ST/test_frozen_record_fields.py:127`, `ST/test_budget_contract.py:65` | `BudgetStage` gains `selector` (budget #22) |
| PR-3 | `ST/data/schemas/screamingface.answer.v1.json`; combine-evidence.v1 abstain enum | abstain reason `budget_refused` |
| PR-3 | `ST/test_gate_docs.py:50-52`, `ST/test_signal_recipes_readme.py:38`, `ST/test_sum_band_docs.py:76-79` | README sentences about the E4b fallback cost (docs #5–#7) |

New goldens and fixtures (no approval needed, they are new files): `ST/data/report_v1_gate_report.json`,
`ET/data/gate_contract/decision_cases.json`, `ET/data/gate_contract/d*.url4`, the
`gate-decision.v1`, `gate-spec.v1`, `keywords.v1`, `label-model.v1` schema snapshots.

## 6. Not tested (with owner, detection and revisit condition)

| What | Why | Detection in production | Revisit when |
|---|---|---|---|
| Live LLMClassifier quality (does a cheap model pick the right label) | model behavior, not platform; offline tests use recorded replies | report: unrecognized/unparsed counts per run | a benchmark shows > 5 % unrecognized |
| Real provider costs against the budget | no paid tests | report: spend vs cap, unpriced warnings | the first paid run with a Budget |
| url4 Part E §24 budget conformance | spec part not in the repo | url4 owner review | Part E is published |
| Parallel race (OME-1465 race form) | out of scope (ans:Q5) | — | OME-559 lands url4 triggers |
| Clusters selector | deferred (ans:Q4) | — | embeddings route exists in aigateway |
