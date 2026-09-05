# OME-1126 — MedXpertQA (Text) as an exact-match MCQ benchmark

**Ticket:** [OME-1126](https://linear.app/openmined/issue/OME-1126/onboard-medxpertqa-text-as-an-exact-match-mcq-benchmark)
· **Ledger:** `docs/work/2026-09-05-OME-1126-medxpert-mcq.md`
· **Stack:** screamingface-engine · **Date:** 2026-09-05

## 1. Problem

We serve five boards, and every one of them grades with an LLM judge. MedXpertQA is
expert-level medical multiple choice: the answer is one letter, graded by string comparison
against a fixed key. That makes it the first board whose grading spends **zero judge tokens**,
and the first to exercise a deterministic grading path end to end.

It is also a credible medical benchmark — 2,450 expert-written questions, MIT-licensed, real
frontier headroom — which is why it is worth serving on its own merits.

A prior experiment (LiveTruth_leaderboard_work, 2026-07-18: 2,450 rows, 15 systems, $1,764) found
that **no fusion beat its own best solo panelist** here, and that richer per-choice confidence
signals did not change that. The owner decision is to onboard it NEUTRALLY regardless: this is a
benchmark, not an argument. The board makes no claim about which candidate shape should win, and
its description does not editorialise about fusion.

## 2. Established facts

Verified 2026-09-05 against the dataset and the code. None assumed.

- **F1 — the data.** `TsinghuaC3I/MedXpertQA`, config `Text`, split `test` = **2,450 rows**
  (`dev` is 5 demo rows). Features `id, question, options, label, medical_task, body_system,
  question_type`. Licence MIT. Sha `7e7c465a68eb2b866926bfa59c8c9d17a8daba65`.
- **F1a — the question ALREADY CONTAINS the choices.** Measured over 100 sampled rows: every
  `question` embeds `"Answer Choices: (A) … (J) …"`, `options` is a DICT keyed A-J (not a list),
  every row carries exactly 10 options, and every `label` is a valid key of its own `options`.
  The prompt therefore uses the question VERBATIM; rendering `options` into it as well would
  duplicate the choice list and quietly change the prompt every model sees.
- **F2 — the official protocol is two-turn.** Turn 1 is `"Q: {question}\nA: Let's think step by
  step."`; the reasoning becomes an assistant turn; turn 2 sends ONLY
  `"Therefore, among A through {end}, the answer is"`, where `{end}` spans the row's own option
  count.
- **F3 — the message layout is what makes extraction correct.** Turn 2 is a bare
  sentence-completion, so the committed letter comes FIRST. Gluing the trigger onto a one-shot
  prompt produces letter-LAST essays; the experiment measured that misread at **35.5% against a
  true 70.2%** on the same essays.
- **F4 — two parsers, deliberately different.** Answer time: FIRST match, restricted to the row's
  option range, after cutting an echoed trigger (verbatim-official). Grading time: LAST match
  with guards, because prose concludes at the end. The experimental code carries explicit
  "NOT the same as" notes in both directions.
- **F5 — an unparsed completion is WRONG, not rescued.** The official harness treats an empty
  prediction as incorrect. The raw completion must never reach the grading-time parser, whose
  lenient net would rescue rows the reference kills.
- **F6 — `max_tokens: 8192`.** 2,048 starves reasoning models into empty answers, which
  silently changes the coverage denominator rather than the score.
- **F7 — the Engine invokes `$candidate` as an opaque recipe.** `benchmarks/candidate_adapter.py`
  evaluates the candidate's compiled expression statelessly per request;
  `ensemble/policy.py` states that the client compiles the whole candidate expression and the
  Engine "contributes generic invocation". A board cannot reach inside a fusion.
- **F8 — IFEval is the structural precedent.** The only other deterministic board: one asset
  bundle, flat module constants rather than the multi-board `exam.py` factory, and five routes
  (`cases`, `check`, `check-surface`, `case-evaluation`, `aggregate`).
- **F9 — the spine exists.** `benchmarks/spine/` (OME-1024) owns `CaseGrader` and `RowReader`;
  HealthBench and GDPval are already migrated onto it.

## 3. Decisions

- **D1 — one board, flat constants, IFEval shape.** MedXpertQA serves a single identity over a
  single asset bundle, so it takes IFEval's module-level `BENCHMARK_ID` / `REVISION` form rather
  than the `exam.py` board factory HealthBench and DRACO need for their multiple boards.
- **D2 — two-turn CoT is imposed at the CANDIDATE BOUNDARY, and the fusion case is a NAMED
  DEVIATION.** The board invokes `$candidate` twice per case: once for reasoning, once for the
  commit whose input carries that reasoning. For a solo model this reproduces the official
  protocol exactly. For a fusion it does not: the experimental implementation ran two-turn per
  member and fed the synthesiser the panel's full analyses, which is not expressible when the
  Engine treats the candidate as opaque (F7).

  Named, not reframed — following the house practice in `healthbench/pins.py`
  ("not expressible through the gateway yet; named deviation") and `gdpval/pins.py`. The board
  description states that a fusion's exchange happens at the candidate boundary and its numbers
  are therefore not comparable to a per-member implementation.

  Rejected: appending the trigger to a one-shot prompt. It is cheaper and uniform, and it is
  wrong by 35 measured points (F3).
- **D3 — both parsers ship, and neither is reused for the other's job.** Answer-time extraction
  is verbatim-official; grading-time extraction is the lenient net for arbitrary text. Their
  docstrings each name the other and say why they differ.
- **D4 — no letter means an empty answer** which the grader scores wrong (F5).
- **D5 — build on `spine`.** `CaseGrader` and `RowReader` are used from the start; MedXpert adds
  no third copy of the reducer. INVARIANT from `spine/__init__.py`: a spine consumer must not
  edit `benchmarks/aggregation.py` or `benchmarks/contract.py`.
- **D6 — preserve `question_type`, `medical_task`, `body_system`** in the baked assets so
  per-slice sub-scores can be reported against the official leaderboard's own cuts.
- **D7 — scoring is plain accuracy over selected cases**, with a coverage figure alongside. See
  the consequence in §6 about comparing systems whose coverage differs.
- **D8 — turn-1 reasoning is preserved in the BOARD's own artifact, not the shared candidate
  envelope.** `contract.CandidateInvocation` carries exactly `status, output, finish_reason,
  refusal, execution, operations` — there is no slot for auxiliary text, and adding one would
  edit `contract.py`, which D5's invariant forbids.

  So the expression binds the reasoning separately and posts
  `{reasoning, commit}` to this board's own `check` route, whose envelope schema MedXpert owns
  outright (`case_evaluation.py`). The shared candidate envelope still records the COMMIT, which
  is the answer being graded.

  WHY preserve it at all: a letter with no reasoning is unauditable. When a model scores badly
  the only available question is whether it reasoned poorly or merely failed to commit, and the
  reasoning is the difference. It is also what the two-turn protocol exists to elicit — discarding
  it would keep the cost of the protocol while throwing away its product.

## 4. Design

New package `benchmarks/medxpert/`, following IFEval:

| Module | Responsibility |
|---|---|
| `definition.py` | `BENCHMARK_ID`, `REVISION`, routes, `_build`, `install_medxpert` |
| `pins.py` | dataset + revision, preparer revision, protocol revision, `max_tokens` |
| `prompts.py` | the CoT template and the trigger template, byte-frozen |
| `answering.py` | `format_trigger`, `extract_choice_letter` (answer-time, FIRST match) |
| `grading.py` | `extract_letter` (grading-time, LAST match) + `grade` |
| `prepare.py` | `prepare(out)` -> `cases.json` (+ metadata slices), audit summary |
| `case_evaluation.py` | bind one checked attempt into the per-case artifact |
| `aggregate.py` | reduce cases via `spine.CaseGrader` + `spine.RowReader` |
| `runtime.py` | the five route handlers |

**Routes** (five, IFEval's set): `cases`, `check`, `check-surface`, `case-evaluation`,
`aggregate`, all under `/benchmarks/medxpert/<revision>/`.

**Case input.** The baked `input` is the row's `question` field verbatim (F1a) — the choices are
already in it. `options` is baked only to derive the trigger's `{end}` and to validate the label;
it is never appended to the prompt.

**Expression** — proven to render and parse before this spec was accepted. Per case:
`reasoning = candidate(cot_prompt)`, then
`commit = candidate(struct{question, reasoning, trigger})`. The `check` route receives
`struct{reasoning, commit}` — not the bare commit — extracts the letter from the commit, and
compares it to the private key. `preserve_candidate_outcome` binds the COMMIT invocation as the
candidate outcome; the reasoning reaches the report through this board's own case-evaluation
envelope (D8), because the shared invocation envelope has no field for it.

**Revision** hashes: dataset + revision, preparer revision, protocol revision, prompt template
bytes, trigger template bytes, and the answer-time extractor's revision. Prompt bytes participate
because a changed prompt is a changed exam.

## 5. Error handling

- A row whose `options` cannot be parsed, or whose `label` is not one of them, fails the BUILD.
- An unparseable commit yields `""` -> graded wrong (D4). It is not an error.
- A candidate invocation that errors is a failed case with a named code, via `spine.CaseGrader`'s
  existing ladder — not a silent zero.
- The frozen case count is asserted at build time; a dataset that grew or shrank fails loudly
  rather than serving a differently-sized exam under the same identity.

## 6. Consequences

- **Two candidate invocations per case.** Roughly 2x the generation cost of a single-invocation
  board — and for a fusion, two complete fan-outs per case. Grading is free, so total cost is
  still far below GDPval.
- **Fusion numbers are not comparable to the experimental implementation** (D2). This must be in
  the board description, not only in the code.
- **Coverage denominators can differ between systems.** A model that returns empty content on a
  chunk of rows is scored over fewer rows than one that answers all of them. The prior run hit
  this. Accuracy alone is therefore misleading across systems, which is why coverage is reported
  beside it (D7).
- **Rankings are not stable under subsampling.** The prior run measured Spearman 0.59 between
  subsamples at temperature 0. A `limit=N` run is a smoke test, not a ranking.

## 7. Test plan

`test_medxpert_answering.py` — first-match extraction inside the option range; echoed-trigger
cutting; a letter outside the range is not returned; no letter yields None.
`test_medxpert_grading.py` — last-match extraction on prose; the "E. coli" and article-"a" guards;
an empty answer grades wrong; the two extractors disagree on a letter-last essay, which is the
regression that pins F3/F4.
`test_medxpert_prepare.py` — 2,450 cases baked; option/label validation fails the build; metadata
slices preserved; re-run is byte-identical; **the baked input equals the source question exactly,
with no re-rendered choice list** (the F1a regression).
`test_medxpert_definition.py` — `case_count == 2450`; revision changes when any hashed input
changes, including the prompt bytes; the expression parses and contains two candidate invocations.
`test_medxpert_aggregate.py` — accuracy over selected cases; coverage reported; a failed
invocation is a visible failed case, never a zero.

## 8. Out of scope

The `MM` config (2,000 rows, needs images). Per-member fusion protocol (F7 — not expressible).
Sub-score reporting on the leaderboard surface; the metadata is preserved (D6) but publishing the
cuts is separate work.
