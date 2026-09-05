# OME-1126 — MedXpertQA implementation plan

> **For agentic workers:** work task-by-task; steps use `- [ ]`. The stack loop is `sdlc-python`.

**Goal:** Serve `medxpert` — 2,450 MedXpertQA Text rows under the official two-turn CoT protocol,
graded by exact letter match with zero judge tokens.

**Architecture:** A new `benchmarks/medxpert/` package on IFEval's flat single-board shape (five
routes, module-level constants), reducing through `spine.CaseGrader` + `spine.RowReader`. The
board invokes `$candidate` twice per case — reason, then commit — which is the official protocol
for a solo and a NAMED DEVIATION for a fusion (spec D2).

**Tech Stack:** Python 3.12+ · uv · pytest · pyright · ruff

**Spec:** `docs/spec/2026-09-05-OME-1126-medxpert-mcq.md`
**Ledger:** `docs/work/2026-09-05-OME-1126-medxpert-mcq.md`

## Global constraints

- **Gates (repo root):** `uv run .claude/scripts/run_gates.py screamingface-engine`
- **Tests are append-only.** Changing a prior test is a 95%-gate STOP.
- **Commit body carries** `Refs: OME-1126`. Never `Co-Authored-By`. Never commit to `main`.
- **Files stay ≤450 lines.** Semantic anchors only: `WHY:` `INVARIANT:` `AIDEV-NOTE:` `FEATURE:` `STORY:`.
- **Do NOT edit `benchmarks/aggregation.py` or `benchmarks/contract.py`** — spine invariant;
  OME-932/OME-934 own them. If something seems to need it, STOP.
- **Runner Jobs are offline with a read-only disk.** All dataset work happens in `prepare`.
- **Prompt bytes are exam identity.** Any change to the CoT or trigger template changes the
  revision.

## File structure

| File | Responsibility |
|---|---|
| `medxpert/pins.py` (create) | dataset + revision, preparer/protocol revision, `max_tokens` |
| `medxpert/prompts.py` (create) | CoT template + trigger template, byte-frozen |
| `medxpert/answering.py` (create) | `format_trigger`, `extract_choice_letter` — FIRST match, official |
| `medxpert/grading.py` (create) | `extract_letter` — LAST match, guarded — and `grade` |
| `medxpert/prepare.py` (create) | `prepare(out)` → `cases.json`; audit summary |
| `medxpert/case_evaluation.py` (create) | bind `{reasoning, commit}` into the per-case artifact |
| `medxpert/aggregate.py` (create) | reduce via `spine.CaseGrader` + `spine.RowReader` |
| `medxpert/runtime.py` (create) | the five route handlers |
| `medxpert/definition.py` (create) | id, revision, routes, `_build`, `install_medxpert` |
| `benchmarks/builtins.py` (modify) | register `MEDXPERT` + its asset bundle |

---

## Task 1: The two extractors

The regression that cost the prior implementation 35 points lives here. Both parsers ship; neither
does the other's job.

- [ ] RED `test_medxpert_answering.py`: first-match inside the option range; an echoed trigger is
      cut before matching; a letter beyond the row's range is not returned; no letter → `None`;
      `format_trigger` spans the row's actual option count.
- [ ] RED `test_medxpert_grading.py`: last-match on prose ("B is tempting, but the answer is D");
      the `E. coli` guard; the article-"a" guard; an empty answer grades wrong.
- [ ] RED the crossover test — **one letter-last essay, both parsers, different answers.** This is
      the F3/F4 regression: it must stay visible in the suite forever.
- [ ] GREEN `pins.py`, `prompts.py`, `answering.py`, `grading.py`.

**Watch:** copy the prompt templates byte-for-byte from the experimental port. They are hashed
into the revision, so a stray space is a different exam.

## Task 2: Prepare

- [ ] RED `test_medxpert_prepare.py`: 2,450 cases; a label outside its own `options` fails the
      build; a row whose `options` is not a 10-key A–J dict fails the build; metadata slices
      preserved; re-run byte-identical; **baked input equals the source question exactly** (the
      F1a regression — no re-rendered choice list).
- [ ] GREEN `prepare.py` with a lazy `datasets` import and an audit summary (OME-925 contract).

**Watch:** `options` is a dict, not a list. It is baked to derive the trigger and validate the
label — never appended to the prompt.

## Amendment (2026-09-05, during Task 2)

Tasks 3-5 are merged into one unit. `test_the_family_guard_covers_every_family_preparer_package`
derives the family set from disk (`benchmarks/*/prepare.py`) and asserts it equals the families
registered in `BUILTIN_DEPLOYMENT`. A `prepare.py` that exists without a registration is therefore
an INCOMPLETE STATE by the repo's own definition, and the tree cannot be green between them.

The original split assumed the gate would tolerate that gap. It does not — deliberately, because
the invariant makes an orphaned preparer impossible to ship. Registration moves into the same
unit as the board.

## Task 3: The board, its runtime, and registration (merged 3+4+5)

- [ ] RED `test_medxpert_definition.py`: `case_count == 2450`; the revision moves when any hashed
      input moves, **including the prompt bytes**; the rendered expression parses and contains
      exactly TWO `/benchmarks/candidate` invocations; `check` receives `{reasoning, commit}`.
- [ ] GREEN `definition.py`, `prompts.py` wiring.

**Watch:** the two-invocation shape is already proven to render and parse — reuse that structure
rather than re-deriving it.

## Task 4 (folded into Task 3): Runtime, evaluation and aggregate

- [ ] RED `test_medxpert_case_evaluation.py`: `{reasoning, commit}` binds; a missing commit fails;
      schema and case_id are enforced.
- [ ] RED `test_medxpert_aggregate.py`: accuracy over selected cases; coverage reported beside it;
      a failed invocation is a VISIBLE failed case, never a silent zero.
- [ ] GREEN `case_evaluation.py`, `aggregate.py` (via spine), `runtime.py`.

## Task 5 (folded into Task 3): Register — and close

- [ ] Register in `builtins.py`; extend the exhaustive registry enumerations that will fail
      (`test_benchmark_protocol`, `test_benchmark_display_metadata` ×2, `test_benchmark_deployment`,
      the family guard). Extended, never relaxed — flag each in the ledger.
- [ ] Full gate run; fill the ledger Outcome; commit with `Refs: OME-1126`; PR.

## Deliberately deferred

- A real graded run. Nothing here produces a score; a `limit=N` smoke test is the first one, and
  per spec §6 it is a smoke test, not a ranking (Spearman 0.59 at temp 0).
- Sub-score reporting on the leaderboard surface (metadata is preserved; publishing is separate).
- The SDK CLI entry and an example notebook — the `py-screamingface` landing, a sibling ticket.

## Execution record (filled during implementation)
