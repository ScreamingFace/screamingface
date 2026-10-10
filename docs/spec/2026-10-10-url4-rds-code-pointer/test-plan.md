# Test plan — url4 code-pointer intents

The rows are in [prd/rds-code-pointer.md §6](prd/rds-code-pointer.md#6-tdd-plan). This
file says where the rigor goes, how the formal model becomes tests, and what must stay
green outside url4.

## 1. Risk and rigor

| Risk | I × L | Rigor | Rows |
|---|---|---|---|
| A relative-URI intent still reaches a model (some group site not routed), or an absolute URI reaches code | H×H | one row per site; assert no processor fetch and no `process` call | 3, 4, 13, 14, 16, 20, 22 |
| The classifier takes an expression for a code pointer, or the reverse | H×H | one case per B §5.2 detection row, with the traps | 1, 2 |
| An input is lost, moved or changed | H×H | property tests from the Lean theorems + a seeded byte corpus | 9, 11, 12, 15, 25 |
| The gate calls the code with the wrong set, or not at all | H×M | property tests from the Lean theorems | 10, 19 |
| Sources run for a group that cannot run (cost) | H×M | spy IO counts fetches | 13, 17 |
| A permanent failure is retried | M×M | status ↔ class table | 18, 23 |
| `@` leaks into protocol params | H×M | separate readers | 5, 6 |

## 2. From theorems to tests

The Lean model (`formal/`) states each rule once. The Python suite checks the
implementation against the same statements. Property tests use a seeded
`random.Random` (no hypothesis dependency, as `T/unit/test_characterization.py`).
Each property test names its theorem in the docstring.

| Lean theorem | Python check | Row |
|---|---|---|
| `IntentForm.specMode`, `v1_not_conforms_iff`, `v1_act_eq_invokeLocal_iff` | table test over every `IntentForm` (only `RELATIVE_URI` reaches the code table) | 2, 4 |
| `find?_pos_bind`, `length_bind`, `pairwise_pos_bind` | `test_binding_matches_model` | 9 |
| `payload_bind_reweigh` | `test_weight_never_filters_delivery` | 9 |
| `gate_mono`, `gate_eq_false_of_required_failed`, `gate_all_of_all_optional` | `test_gate_matches_model` | 10 |
| `calls_aggregate`, `length_calls_broadcast`, `head?_inputs_of_mem_calls_broadcast`, `length_inputs_of_mem_calls_broadcast` | call-count spies | 14, 20 |
| `resolvedCount_expandWith_expand`, `unnamed_expansions_collide` | expansion tests | 12 |
| `evalGroup_unsupported`, `evalGroup_unmounted`, `evalGroup_exec`, `evalGroup_ne_exec_of_gate_false` | preflight and gate integration | 4, 17, 19 |
| `exists_intentError_of_toOutcome_eq_failed` | handler-failure mapping | 18 |
| `cls_inbound_statusOf`, `inbound_statusOf` | status table test | 23 |
| `v1_strictFields_iff`, `specMode_eq_rds_of_strictFields` | strict-scope tests (bare-token groups stay lenient) | 21 |

A reference implementation of `bind` and `gate` in the test module (a direct transcription
of the Lean definitions, about 30 lines) is the oracle for rows 9 and 10.

## 3. Ground rules

- RED first: run each new test and see it fail on an assertion.
- CHAR first: write CH11 before any delta row, and run it green on today's code.
- Flips: CH9 and the CH11 rows marked *flips* change in the commit that changes the
  behavior. All other existing url4 tests stay as they are.
- New files: `T/spec/test_rds_code_pointer.py` (spec level), `T/unit/test_intent_classify.py`,
  `T/unit/test_code_binding.py` (properties). The `query-tail` cases append to
  `T/spec/test_param_conformance.py`.

## 4. Lanes

| Lane | Runs | Command (from `packages/url4`) |
|---|---|---|
| url4 unit + spec | rows 1–24 | `uv run pytest tests/unit tests/spec` |
| url4 e2e | row 25 | `uv run pytest tests/spec/test_rds_code_pointer.py -k e4a_vote` |
| url4 gates | ruff, pyright, coverage, module size, suppressions, layering, ratchets | the package CI job |
| Formal model | `lake build` (fails on any `sorry` or extra axiom through `#assert_axioms`) | `cd formal && lake build` |
| Engine | full suite, no test edits | the Engine CI job |
| SDK | full suite, no test edits | the SDK CI job |

A red Engine or SDK test is a finding, not a test to update.

## 5. Release checks

- Squash commit `feat(url4)!: run code-pointer intents as RDS calls` with a
  `BREAKING CHANGE:` footer; release-please writes the CHANGELOG (do not edit it by hand).
- "Migrating to 2.0" section in `packages/url4/README.md` (overview §9).
- `packages/url4/ARCHITECTURE.md`: the group-site table gets the `CodeCallNode` row, and
  the task index lists `core/intent.py` and `core/code.py`.
- The Lean model moves with the spec (or into `packages/url4/formal/` if the owner wants
  it in CI).
