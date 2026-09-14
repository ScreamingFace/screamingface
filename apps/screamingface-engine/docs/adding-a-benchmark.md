# Adding a benchmark

**TLDR: a benchmark is an exam. You bring the question paper (dataset mapping), the
marking rule (`grade_case`), and the cover sheet (declaration); the shared spine runs the
exam hall.** You never edit another board or a shared spine file — if you have to, the
spine failed its deletion test and that is a bug to file, not a pattern to copy.

Think of every benchmark as an exam with four fixed steps: hand out the question paper,
collect the answer sheets, mark each script, publish the report card. The spine
(`src/screamingface_engine/benchmarks/spine/`) owns steps 1, 2 and 4 — selection, row
decode, the failure ladder, aggregation, publication. **A board author writes only the
marking rule and the exam's cover sheet.** The realistic size, from the boards in
production: a rubric board on the shared factories is ~122 lines of grading code
(`gdpval/grade.py`, `healthbench/grade.py` — both exactly 122); a board with a novel
grading mode is larger (`medxpert/aggregate.py` 245, `ifeval/grade.py` 401) plus its
protocol/runtime modules.

Everything below is walked against MedXpertQA (`benchmarks/medxpert/`), the newest board
— when a step says "copy the shape", that is the module to open.

## Step 0 — pick your two axes

Every benchmark declares two choices up front, on the exam's cover sheet
(`BenchmarkDeclaration`, `benchmarks/definition.py`). Both are required with no defaults:
a defaulted policy is a policy nobody can approve from the manifest.

| Axis | Values today | Later (declared, not built) |
|---|---|---|
| `interaction` — how the Candidate is exercised | `single_shot` (one prompt, one reply — draco, ifeval, healthbench, gdpval) · `multi_turn` (the board invokes the Candidate more than once per Case — medxpert) | agentic / tool-environment values; an `environment` declaration (image digest + setup + verifier) lands as a new field on `BenchmarkDeclaration`, never as a spine change |
| `failure_policy` — what a Case that never got a valid grade does to the score | `coverage_declare` (all 7 boards) · `withhold` (valid, zero users) | — |

`failure_policy`, in exam terms: an exam of 157 questions where 33 answer sheets got lost
in the mail. `withhold` counts the lost sheets against the candidate (score = earned /
157, coverage always reads 100%, an infra outage makes the model look worse).
`coverage_declare` excludes them and says so (score = earned / the 124 graded, published
next to "scored 124 of 157", each excluded Case keeping a named failure code). Neither is
wrong — but they produce different numbers from identical model behavior, which is why
the choice is declared per benchmark and published in the manifest for reviewers to
approve.

There is a third, informal axis: **the grading mode**, `ScoredPath.method` — a free
string published as `CaseGrade.method` on every result. Values in production: `"rubric"`
(judge model marks against rubric points), `"deterministic"` (vendored checker code),
`"exact_match"` (committed letter vs private key). **`method` is the one axis nothing
validates — a typo ships to the leaderboard.** Reuse an existing value unless your
grading genuinely is a new kind.

## Step 1 — the board module

One directory: `src/screamingface_engine/benchmarks/<board>/`. MedXpertQA's layout, with
each file's role:

| File | Role (exam terms) |
|---|---|
| `pins.py` | which printing of the question paper — dataset id, config, revision, split, plus `PREPARER_REVISION` / `PROTOCOL_REVISION` |
| `prepare.py` | prints the paper — dataset → baked assets, at image build time |
| `definition.py` | the exam's public listing — the `Benchmark` record, `compute_revision()`, the url4 protocol template, the declaration |
| `runtime.py` | the exam hall's doors — the board's FastAPI routes |
| `aggregate.py` | the marking room — `grade_case`, the `ScoredPath` wiring, the scorer |
| `grading.py` / `answering.py` / `prompts.py` | board-private marking and prompting helpers |

Unit tests go to `tests/unit/test_<board>_*.py` (medxpert ships seven). Spine tests
(`test_spine_*.py`) are not yours to touch.

## Step 2 — prepare the assets

Convention: `prepare.py` exposes `def prepare(out: Path) -> dict[str, Any]` returning an
audit summary, plus an argparse `main()` with `--out`. It runs at **image build time
only** (`Dockerfile.benchmark`), never at request time. MedXpertQA's invocation:

```sh
uv run --with datasets python -m screamingface_engine.benchmarks.medxpert.prepare \
    --out /opt/benchmarks/medxpert
```

Rules that bind every preparer:

- **Split public from private on disk.** MedXpertQA writes `cases.json` (all a client
  ever sees) and `answers/<id>.json` (the answer key — read only by `runtime.py` and
  `aggregate.py`). The rubric goes only to the examiner; a leak is cheating.
- Heavy dataset deps (`datasets`) are **not** engine dependencies — import them lazily
  inside `prepare` (`importlib.import_module`), so the runtime image stays clean.
- Dataset drift (schema change, missing rows) raises a `BenchmarkAssetPreparationError`
  subclass — reported without a traceback. `TypeError`-family stays reserved for
  programming defects (`benchmarks/deployment.py`).
- Pin everything in `pins.py` and fold it into `compute_revision()` (sha256[:16] over
  pins + prompt templates, see `medxpert/definition.py`). The revision is part of every
  route path, so a re-print of the paper is a new, distinguishable exam.

Assets land under `$URL4_BENCHMARK_ASSETS` (default `/opt/benchmarks`), one subdirectory
per bundle id. All bundles: `python -m screamingface_engine.benchmarks.prepare --root
<path>`. Two boards may share one bundle (draco/draco-3pass do; both healthbench boards
do).

## Step 3 — the case-row shapes

Two row shapes, one public, one board-owned:

**The baked dataset row** (`cases.json`): a JSON array of objects, each with an `int`
`id` and a non-blank `str` `input`. Every other key rides through as Case metadata. The
spine decodes it into `SelectedCase` (`benchmarks/aggregation.py`) — `case_id`, `input`,
`metadata` — and hands your board the id when it needs grading material.

**The evaluation row** your `grade_case` receives: an **opaque, board-owned envelope**
(`spine/rows.py` files it and never looks inside). Your `RowReader.decode_case_evaluation`
shapes it. The one sub-key the spine does read is `row["case"]` — a mapping with the
candidate fields `status`, `output`, `finish_reason`, `refusal`, `execution`,
`operations`, `metadata` — so your decode must hoist that mapping (copy
`medxpert/aggregate.py` or `ifeval/grade.py`).

Inputs and answers cross the seam as **kind-tagged payloads** (`spine/payloads.py`).
`TextPayload` (`kind="text"`) is the only kind implemented; `text+attachments` and
`environment` are named in the union's AIDEV-NOTE and arrive as new dataclasses, never as
a spine rewrite.

## Step 4 — write `grade_case`, the marking rule

The seam every benchmark implements (`spine/scored.py`):

```python
type GradeCase = Callable[[GradeRequest], Awaitable[CaseGradeOutcome]]
```

Async because the call may be a network hop (an enclave judge); data-only because nothing
else crosses a privacy boundary. What crosses, verbatim from the spine:

```python
@dataclass(frozen=True, slots=True)
class GradeRequest:
    case_id: CaseId
    input: CasePayload  # what the Candidate was asked
    answer: CasePayload | None  # what it answered; None when no usable answer text
    row: Mapping[str, Any]  # your board-decoded evaluation envelope
    material: object  # your grading material — opaque to the spine


@dataclass(frozen=True, slots=True)
class CaseGradeOutcome:
    score: float | None  # a graded Case carries score, failure_code=None
    metrics: Mapping[str, Any]  # board vocabulary, not spine vocabulary
    checks: Sequence[Mapping[str, Any]]  # Check-shaped dicts (contract.py)
    failure_code: str | None = None  # names WHY an ungraded Case failed
```

**INVARIANT (the hourglass waist): a `GradeRequest` carries only plain, serializable
data** — kind-tagged payloads, the decoded row mapping, the board's grading material. No
`Path`, no engine objects, no callbacks. Three consumers force this: an enclave judge
across a privacy boundary, the inspect_evals scorer shim, and agentic boards.

The worked example — MedXpertQA's whole marking rule, 28 lines
(`medxpert/aggregate.py`):

```python
async def _grade_case(request: GradeRequest) -> CaseGradeOutcome:
    """Exact-match one committed letter against the private key — the whole exam rule."""
    attempt: Mapping[str, Any] = request.row["attempt"]
    material = request.material
    assert isinstance(material, Mapping)  # the ladder already rejected unusable assets
    label: str = str(material["label"])
    committed: str = str(attempt.get("answer") or "")
    answered: bool = bool(committed)
    correct: bool = answered and committed == label
    return CaseGradeOutcome(
        score=1.0 if correct else 0.0,  # unanswered scores 0.0, not None —
        metrics={"answered": answered},  # the official empty-prediction verdict
        checks=[
            {
                "type": "choice",
                "id": "1",
                "label": "committed choice matches the published key",
                "outcome": "MET" if correct else "UNMET",
                "evidence": [_match_evidence(committed, label, correct)],
                "metadata": {"committed": committed, "expected": label},
            }
        ],
    )
```

Read the example's grammar: `material` is the answer key your board baked in Step 2
(rubric points, a label, later a verifier command); `row` is your own envelope from Step
3; the returned `checks` are `Check`/`Evidence`-shaped dicts (`benchmarks/contract.py`)
so the judge's work is auditable per Case.

**Rubric boards don't write this at all.** The shared factory gives you the judged
marking rule in one line (`spine/rubric.py`):

```python
grade_case = rubric_grade_case(case_score=case_score, judge_producer_id="gdpval/judge")
```

where `case_score: (points, verdicts) -> float | None` is your board's official scoring
formula. The factory owns the two rubric failure codes: `"incomplete_verdicts"` (the
judge didn't return a usable verdict for every criterion) and `"no_positive_points"`
(fully judged, nothing worth points). Judge replies are parsed by the one shared parser
(`spine/verdict.py`) — never write your own.

## Step 5 — declare the cover sheet and wire the path

The declaration (both fields refused by name at construction if invalid):

```python
declaration = BenchmarkDeclaration(
    failure_policy="coverage_declare",
    interaction="multi_turn",  # medxpert; single_shot for most boards
)
```

The invariant every board factory repeats: **declare `withhold` only if your aggregate
actually withholds.** Every current board reduces through the shared path, which scores
exactly the gradeable subset and publishes coverage — that is `coverage_declare`. The
declaration is splatted unconditionally into the catalog entry and the manifest:
reviewers approve your policy by reading the manifest, never engine source.

Then bundle the hooks into a `ScoredPath` (`spine/scored.py`) — MedXpertQA's is the
smallest complete registration of the whole surface (`medxpert/aggregate.py`):

```python
_PATH = ScoredPath(
    reader=RowReader(...),  # your decode from Step 3
    grade_case=_grade_case,  # your marking rule from Step 4
    failure_messages=...,  # your board's wording per failure code
    method="exact_match",
    grading_failure_code=...,
    grading_failure_message=...,
    missing_material_code="missing_answer_asset",  # default: "missing_rubric_asset"
)
```

and call `_PATH.aggregate(raw_rows, benchmark_id=..., benchmark_revision=...,
selected_cases=..., grading_material=..., scorer=..., case_metadata=...)`. The spine's
failure ladder runs in this order before your `grade_case` ever sees a row: grading
failure → your `error_row_result` hook (if set) → missing material → missing row → error
row → gradeable. Four optional hooks let a board reshape a rung's result — `ifeval` sets
`missing_row_result` (a collected error row becomes a `grading`-stage failure); `draco`
sets all four. Don't set any until a golden or a spec forces you to.

For the scorer: rubric boards use the shared `exam_scorer(mean)` (`spine/exam.py`), which
fixes the metric vocabulary (`pass_rate`, `scored_cases`, `score_sd`,
`verdict_coverage`, `judge_invalid_replies`). Other boards pass their own function —
medxpert's `_accuracy`, ifeval's `_ifeval_score`.

The protocol surface — the url4 template in `definition.py` (`build`) plus the FastAPI
routes in `runtime.py` (`install`) — follows one rule: **one explicit route per
operation, revision in the path** (`ROUTE_PREFIX = f"/benchmarks/{BENCHMARK_ID}/{REVISION}"`).
Registration refuses a benchmark whose rendered protocol references a route `install`
never registered, so a missing route fails at startup, not mid-run. Copy
`medxpert/definition.py` + `medxpert/runtime.py`; the shapes are not summarized here on
purpose — those two files are the source of truth.

## Step 6 — register

A flat, hand-edited list — no entry points, no discovery. Three edits in
`benchmarks/builtins.py`:

1. Import your `Benchmark` and `ASSET_BUNDLE_ID`.
2. Add a lazy prepare shim + bundle:
   `MEDXPERT_ASSETS = BenchmarkAssetBundle(id=MEDXPERT_ASSET_BUNDLE_ID, prepare=_prepare_medxpert)`.
3. One line in `BUILTIN_DEPLOYMENT`:
   `BenchmarkRegistration(benchmark=MEDXPERT, asset_bundle=MEDXPERT_ASSETS)`.

And one edit outside the engine: add the board id to `_BENCHMARKS` in
`packages/screamingface/src/screamingface/_runtime/cli.py`, which backs
`screamingface prepare <benchmark>` on the client.

## Step 7 — protect the score

Unit tests first (`tests/unit/test_<board>_*.py`): the marking rule's happy path,
boundaries, and every failure code you can produce. Then the e2e replay lane — the
recorded tape that locks your published score against refactors. The full procedure
(register → one paid run → bless → commit the tape) is the e2e README:
[`packages/screamingface/tests/e2e/README.md`](../../../packages/screamingface/tests/e2e/README.md).
Its short shape: a dev wires the board into the lane (it SKIPs loudly until fixtures
exist), the owner pays for exactly one recorded run, the dev blesses it with
`just e2e-bless <board> <model> <dump.sql.gz> <answers.jsonl> --expect-score <score>`,
and CI thereafter replays with zero API keys, going red on any of five locks —
expression sha, case statuses, failure codes, coverage, score.

## Decision — `grade_case` reviewed as a public seam (2026-09-14, OME-1102)

The hook was extracted by the team that built the spine; before calling it a contract we
checked it against two external shapes.

**Shape 1 — the MedXpertQA row mapping** (now merged): needed no sibling handler and no
spine edit. It exercised the seam's least-used corners — a non-rubric method, `multi_turn`
interaction, a board-named `missing_material_code`, `case_metadata` — all through
declared extension points. Pass.

**Shape 2 — an in-enclave refusal judge (Crucible-shaped): pass, with one recorded
caveat.** The checks:

- The request is plain serializable data (the hourglass invariant) — it can cross a
  privacy boundary as-is. The hook is async, so the enclave hop fits the signature.
- Judge configuration rides in `material` (opaque to the spine) — no signature change
  needed to point a Case at an external judge.
- A refusal's text does **not** ride on `GradeRequest.answer` (that is `None` when no
  usable answer exists); it is reachable through the board-owned `row` envelope, whose
  `row["case"]` mapping carries `refusal`. A refusal judge therefore grades from the
  envelope, which the board controls end-to-end. No sibling handler needed.
- The judge's own words come back inside `checks[].evidence[]`
  (`Evidence.explanation` / `raw_output`), so an external judge's audit trail fits the
  existing result shape.

**Caveat:** this review ran against the shape described in the epic (an in-enclave judge
whose owners approve eval code before running it), not against a contract document from
that judge's owners. If their real interface needs anything beyond an async call with
serializable data in and `CaseGradeOutcome` out, that is a new ticket against
`BenchmarkDeclaration` or the payload union — not a quiet widening of `grade_case`.

## Gotchas — the steps people miss

- **`method` is unvalidated.** `interaction` and `failure_policy` are refused by name at
  construction; a `method` typo ships to the leaderboard.
- **`asset_bundle` has no default** on `BenchmarkRegistration` — a board with no assets
  still decides that explicitly.
- **Registration fails on unrouted protocol references** — if your url4 template names an
  endpoint `install` didn't register, the engine refuses at startup with the missing
  routes by name.
- **A graded Case never carries both `score` and `failure_code`** — one or the other.
- **Case statuses are two:** `scored` | `failed`. A graded refusal is an ordinary scored
  Case carrying `refusal` text; an ungradeable one is a failed Case with the
  `provider_refusal` failure code (OME-1037).
- The five-stage marking-room narrative at the top of `spine/scored.py` is the best
  30-line orientation in the codebase — read it before your first board.

## Related docs

- [`execution-flow-diagrams.md`](execution-flow-diagrams.md) — where your board's
  aggregate gets called from.
- [`request-workflow.md`](request-workflow.md) — the k8s request trace.
- [`packages/screamingface/tests/e2e/README.md`](../../../packages/screamingface/tests/e2e/README.md)
  — the record/bless/replay lane (Step 7).
