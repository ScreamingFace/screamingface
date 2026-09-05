---
ticket: OME-1126
stack: screamingface-engine
status: in_progress
started: 2026-09-05
finished:
---

# OME-1126 — MedXpertQA (Text) as an exact-match MCQ benchmark

## Intent

A prestige medical benchmark with real frontier headroom, MIT-licensed, and the first board whose
grading spends NO judge tokens — an exact string match on a choice letter. It exercises a grading
path none of the five existing boards use, and it is treated as a neutral leaderboard target:
entrants rank, fusions are welcome, and no claim is made about which candidate shape should win.

## Established facts (verified 2026-09-05, none assumed)

- **Dataset.** `TsinghuaC3I/MedXpertQA`, config `Text`, split `test` = **2,450 rows** (`dev` is 5
  demo rows). Features: `id, question, options, label, medical_task, body_system, question_type`.
  Licence MIT. Current sha `7e7c465a68eb2b866926bfa59c8c9d17a8daba65`.
- **The `MM` config is out of scope** — 2,000 rows requiring images.
- **Prior experimental run** (LiveTruth_leaderboard_work, 2026-07-18): full 2,450 rows across 15
  systems, $1,764. Best system was a SOLO (`gemini-3.1-pro`, 72.4%); 0 of 7 fusions beat their
  own best panelist. A follow-up experiment with typed per-choice confidence also failed
  (AUROC <= 0.525; showing the synthesiser the numbers changed accuracy by +0.0%).
  **Owner decision: onboard neutrally anyway.** The board makes no claim about fusion; it is a
  benchmark, not an argument.

## Protocol constants that must be reproduced exactly

Ported from the official harness via the experimental implementation. Each is load-bearing.

- **Two-turn zero-shot CoT.** Turn 1 user content is `"Q: {question}\nA: Let's think step by
  step."`; the model's reasoning becomes an assistant turn; turn 2 sends ONLY the trigger
  `"Therefore, among A through {end}, the answer is"`. `{end}` spans this row's actual option
  count.
- **The message layout is what makes extraction correct**, not any instruction. Because turn 2 is
  a bare sentence-completion, the committed letter comes FIRST. Gluing the trigger onto a
  one-shot prompt produced letter-LAST essays and a measured **-35 point** misread.
- **Two different parsers, deliberately.** At answer time: FIRST match, restricted to the row's
  option range, after cutting any echoed trigger — verbatim-official. At grading time: LAST match
  with guards, because prose concludes at the end. Conflating them is the bug above.
- **No parseable letter -> empty answer -> graded wrong.** The raw completion must never reach the
  grader; its lenient prose net would rescue rows the official harness kills and inflate scores.
- `max_tokens: 8192` — 2,048 starves reasoning models into empty answers. `temperature: 0`.
- Preserve `question_type`, `medical_task`, `body_system` for leaderboard-comparable sub-scores.

## Architectural finding — the load-bearing unknown

Every existing board invokes `$candidate` exactly ONCE. `ensemble/policy.py` states the rule:
the client compiles the whole candidate expression (fan-out, rounds, gates) and the Engine
"contributes generic invocation" — a board never owns the candidate's internals.

MedXpertQA's two-turn CoT is the BENCHMARK's protocol, not the candidate's: every entrant is
evaluated under it, and it is what makes published numbers comparable. So the board must impose a
two-call exchange while `preserve_candidate_outcome` binds exactly one `candidate_invocation`.

Resolving that is the spec's central decision, not an implementation detail.

## Precedent to follow

IFEval is the closest board — deterministic, no judge, one asset bundle, flat module constants
rather than the multi-board `exam.py` template (MedXpert serves one board, so flat is right).
Its route set is five, not seven: `cases`, `check`, `check-surface`, `case-evaluation`,
`aggregate`.

The `spine` package (OME-1024) now owns `CaseGrader` and `RowReader`; both HealthBench and GDPval
were migrated onto it. MedXpert builds on `spine` from the start — no third clone of the reducer.
INVARIANT from `spine/__init__.py`: a spine consumer must NOT edit `benchmarks/aggregation.py` or
`benchmarks/contract.py`; live-progress branches own those.

## Planned changes

All written. `benchmarks/medxpert/{__init__,pins,prompts,answering,grading,prepare,
case_evaluation,aggregate,runtime,definition}.py`, registered in `benchmarks/builtins.py`, with
`tests/unit/test_medxpert_{answering,grading,prepare,definition}.py`.

## Test plan

Written and passing except where blocked below: 29 tests across four files, including the
crossover regression that pins the two extractors apart.

## Acceptance

- `medxpert` registered and served with `case_count = 2450` and a pinned revision hash.
- `sf.evaluate(model, benchmark="medxpert")` returns per-case correctness.
- The answer-time and grading-time extractors are separately tested, including the
  trigger-completion vs prose distinction that caused the -35 point regression.
- An unparseable completion scores wrong rather than being rescued by the grading-time parser.
- Gates green: `ruff check`, `ruff format --check`, `pyright`, `check_layering.py`,
  `pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80`.

## The OME-1039 contract change — PROCEEDING ON OWNER DECISION, PENDING KHOA'S REVIEW

Khoa (OME-1039's owner) is away. Owner decision 2026-09-05: proceed and incorporate his feedback
when it arrives. Nothing here depends on the NAME `multi_turn` — only on the declaration being
able to state the truth, so a different axis, value, or per-board escape can replace it cheaply.

Two guard tests were changed. Both were kept at full strength rather than loosened:

- `test_declaration_refuses_an_unknown_interaction_by_name` named `multi_turn` as its unknown
  value. It now names `agentic_tool_use` — still genuinely unknown — so the guard still proves an
  unknown interaction is refused by name. A companion test was ADDED asserting `multi_turn` is
  accepted, so the value's acceptance is itself pinned rather than merely un-refused.
- `test_every_builtin_board_declares_its_actual_policy` looped over all boards asserting
  `single_shot`. It is now an explicit per-board table. That is STRONGER: a board changing its
  declaration now trips, which a blanket "all single_shot" loop could not detect once a second
  shape existed.

Not taken: declaring `single_shot` and treating the two-turn exchange as internal. The board
genuinely invokes `$candidate` twice, and a manifest that says otherwise defeats the purpose the
declaration exists for.

## Deviations found while building

- **`failure_policy` was wrong in the spec and is corrected to `coverage_declare`.** The spec
  reasoned that the official harness scores an empty prediction wrong, so the board should declare
  `withhold`. That conflated two different things. This axis governs a Case that never got a valid
  grade — an infrastructure failure — and those go to the shared `finalize_candidate_result`,
  which scores the gradeable subset and publishes coverage. An empty ANSWER does get a grade, of
  0.0, in `aggregate._scored`. `test_every_builtin_board_declares_its_actual_policy` caught the
  mismatch, which is exactly its stated job: "the declaration tells the truth about the code".
- **`spine.CaseGrader` is NOT used; `spine.RowReader` is.** The grader is rubric-shaped —
  `points: list[int]` with verdicts-by-position — and emits hardcoded failure codes
  (`missing_rubric_asset`, `incomplete_verdicts`, `no_positive_points`) that a board may reword
  via `failure_messages` but cannot rename. An MCQ board publishing `code:
  "missing_rubric_asset"` would contradict its own message, and `code` is the machine-readable
  field a consumer filters on. MedXpert therefore owns a thin MCQ-native grading path. Row
  indexing is genuinely board-independent and is shared. If a second non-rubric board arrives,
  generalising `CaseGrader` becomes a spine ticket with two data points — per
  `spine/__init__.py`, extraction happens one ticket at a time and never from a consumer.
- **`failure_policy` is declared by every board but consumed nowhere in the scoring path** — it
  reaches `as_block()` and the published manifest only. Not this ticket's to change, but a
  manifest reader could mistake it for a platform guarantee. Raised with Khoa as an FYI.
- **Tasks 3-5 merged** (see the plan amendment): the family guard derives its package set from
  disk and asserts it equals the registered families, so a `prepare.py` without a registration is
  an incomplete state by the repo's own definition.
- **Two of my own test expectations were wrong, not the code.** The crossover essay contained
  " answer is ", which the official parser's own fallback splits on, so it recovered the right
  letter and hid the bug; and a bare "I" IS read as choice I at ten options, which is faithful
  official behaviour and is now pinned as a known hazard rather than silently diverged from.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
