---
status: draft
ticket: unfiled
created: 2026-10-20
components: [screamingface-engine, client-sf, url4-sdk]
---

# Spec: A spec-faithful URL4 expression for imported benchmarks

## 1. Problem

The Engine builds one URL4 expression for each Benchmark run. The expression parses, but it does
not use the grammar as URL4 Parts A–C define it. It uses quoted intents as labels, counts and
identity projections, and it uses iteration as a let-binding and as a try/catch.

This is the expression for a 3-case ContractEval run (`contracteval.resource(3)`, `origin/main`):

```
(case_evaluations:0.0:(selected_case_evaluations:0.0:/benchmarks/contracteval/890889e5b2863be4/cases()!'3'*(evaluated:0.0:(preserved_case:0.0:(candidate_invocation:0.0:(candidate_invocation:0.0:/benchmarks/candidate?web_search=false&context_format=case-v1&q=({input: '$item.input', case_id: '$item.id', case_index: '$index', case_count: '3'})!'$candidate')!'$candidate_invocation', protected_grading:0.0:({candidate_invocation: '$candidate_invocation', case_id: '$item.id'})*(grading:0.0:(record:0.0:/benchmarks/contracteval/890889e5b2863be4/check($candidate_invocation)!'$item.case_id', case_evaluation:0.0:/benchmarks/contracteval/890889e5b2863be4/case-evaluation({attempt_1: '$record'})!'$item.case_id')!'$case_evaluation')!'$grading', case_execution:0.0:/benchmarks/case-execution({case_id: '$item.id', candidate_invocation: '$candidate_invocation', grading: '$protected_grading'})!'')!'$case_execution')!'$preserved_case')!'$evaluated';iteration.concurrency=1;iteration.slice=0:3)!'$selected_case_evaluations', result:0.0:/benchmarks/contracteval/890889e5b2863be4/aggregate($case_evaluations)!'aggregate:3')!'$result'
```

### 1.1 Defects against the URL4 spec

| Fragment | What the URL4 spec reads | Defect |
|---|---|---|
| `/…/cases()!'3'` | An LLM call with no sources and the prompt "3". | The case set is data, not a computation. The route uses the "prompt" only as a count to check, and returns the whole file. |
| `(x:0.0:E)!'$x'` (6 times) | An LLM prompt whose text is a variable. | An identity wrapper. A source carries its own name (B §4.3). |
| `/…/check($candidate_invocation)!'$item.case_id'` | The endpoint is the target. The case id is the prompt. | `check` is deterministic code. Code is an RDS intent (A §1.1, B §6). The case id is an argument. |
| `/benchmarks/case-execution({…})!''` | An empty prompt. | An envelope wrapper. The route ignores the intent. |
| `({…})*( … )` | Iteration over a one-element collection. | Iteration is used to rebind `$item` and to collect a grading error. `;optional` and `iteration.on_error=collect` do this (C §10.1, B §5.3.6). |
| `/…/aggregate($x)!'aggregate:3'` | The prompt "aggregate:3". | An RDS intent. The count is an argument. |
| `/benchmarks/candidate?…q=({input,…})!'$candidate'` | The Candidate recipe is the prompt. The prompt is a struct in the sources. | Inverted. The prompt is `$item.input`. The recipe is an argument. |
| `$index` | Not defined in Parts A–C. | An Engine extension. |

## 2. Design rules

These rules come from URL4 Parts A–C and from the IFEval corrective-ensemble endpoint contracts
(Kevin McDonough, 2026-09-17).

- **R1 — Code is an RDS intent.** A deterministic step is `(named args)!/code/pointer`. The source
  names are the input contract of the code (B §6.3). The Engine mounts each step with
  `node.code(...)`.
- **R2 — A model call is LLM mode.** The endpoint is the target, the sources are the context, and
  the quoted intent is the prompt.
- **R3 — The case set is a data reference.** It has no `!`. The run selects cases with
  `;iteration.slice` (B §5.3.6).
- **R4 — The nesting is the pipeline.** The run terminal is the outer intent. The per-case
  terminal is the intent of the iteration body. Each per-case step is a body source.
- **R5 — Bind arguments explicitly.** A step gets case fields through `src=$item…`. A step does
  not depend on a rebound `$item`.
- **R6 — Failure handling is an annotation.** The iteration is `iteration.on_error=collect`. The
  structure does not change for failure handling.
- **R7 — A quoted intent is a prompt.** No quoted intent is a label, a count or a projection.

## 3. Target expressions

### 3.1 Imported boards (one Attempt)

```
(
  evaluations:0.0:/benchmarks/contracteval/<rev>/cases*(
    case:0.0:src=$item,
    attempt_1:0.0:/benchmarks/candidate?web_search=false&q=(
      case_id:src=$item.id, case_index:src=$index, case_count:src=3, recipe:src=$candidate
    )!'$item.input'
  )!/benchmarks/contracteval/<rev>/case-evaluation;iteration.slice=0:3;iteration.concurrency=1;iteration.on_error=collect,
  selected:0.0:src=3
)!/benchmarks/contracteval/<rev>/aggregate
```

The Client links a Candidate by adding `candidate:0.0:'<recipe URL4>'` as the FIRST source of the
top-level group. The old `(candidate:0.0:'…', <benchmark>)!''` wrapper goes away (R7).

With `attempts=N` (OME-1458), the body has `attempt_1` … `attempt_N`. Attempt `i ≥ 2` adds
`&attempt=i` to its Candidate call. `case-evaluation` returns the `case-attempts.v1` row.

### 3.2 MedXpertQA (two turns)

```
(
  evaluations:0.0:/benchmarks/medxpert/<rev>/cases*(
    case:0.0:src=$item,
    reasoning:0.0:/benchmarks/candidate?web_search=false&q=(<case facts>, recipe:src=$candidate)!'$item.cot_prompt',
    commit_prompt:0.0:(question:src=$item.input, reasoning:src=$reasoning, trigger:src=$item.trigger)!/benchmarks/medxpert/<rev>/commit-prompt,
    attempt_1:0.0:/benchmarks/candidate?web_search=false&q=(<case facts>, recipe:src=$candidate)!'$commit_prompt',
    execution:0.0:(case:0.0:src=$item, reasoning:src=$reasoning, attempt_1:src=$attempt_1)!/benchmarks/medxpert/<rev>/case-evaluation,
    case_index:0.0:src=$index,
    case_count:0.0:src=3
  )!/benchmarks/medxpert/<rev>/aggregate/case-result;iteration.slice=0:3;iteration.concurrency=1;iteration.on_error=collect,
  selected:0.0:src=3
)!/benchmarks/medxpert/<rev>/aggregate/graded
```

`<case facts>` is `case_id:src=$item.id, case_index:src=$index, case_count:src=3`.
`commit-prompt` is deterministic code. It returns the turn-2 model input byte for byte as
today (`json.dumps({"question", "reasoning", "trigger"})`, see `case_request.candidate_input`).

### 3.3 Notes

- **The Candidate context.** The url4 runtime packs the unweighted named sources of an endpoint
  call as `name: value` lines, in source order (`url4/dag/nodes/_shared.py` `_gather`). The
  Candidate endpoint decodes the three fact lines first, then takes the rest after `recipe: ` as
  the recipe. The recipe is LAST, so a recipe with a new line cannot be misread. A `0.0` source
  is not packed, so the facts and the recipe carry no weight.
- **Cache identity.** The Candidate evaluates the same recipe with the same `input_text`, so the
  model-call bytes do not change and the request cache still hits.
- **Candidate failure.** The Candidate call is required, as it is today. A failed Candidate fails
  its case, and the iteration collects it as an error row (same row as today).
- **Grading failure.** `case-evaluation` catches a failure of the per-case check and stores it as
  the `{"error": {...}}` grading outcome, in the url4 collected-error shape. The Candidate answer
  stays in the row for re-grading, as it does today with the protective iterate.
- **Rows do not change.** `case-evaluation` returns the same `case-execution.v1` (or
  `case-attempts.v1`) row as today. `aggregate` reads the same rows, so grading and the report do
  not change.

- **Rendered form.** url4's canonical renderer writes `name=value` / `name:0.0:value` for
  `src=` bindings, quotes bare tokens (`'3'`), and omits `iteration.on_error=collect`
  because it is the default. The AST is the one shown above.
- **`$index`.** Parts A–C define only `$item`; url4 also binds the row index as `$index`. The
  Engine uses it as a Case fact (activity position, early grading), never as model input.
  This is an accepted url4 extension.
- **The Recipe is a literal.** The top-level group ends in code, so it is an RDS scope where
  quoted text is interpolated strictly (B §6.3). The linker carries the Recipe with `$` as
  `$$` (`url4.literal`, B §6.2), and readers use `url4.literal_value`.

### 3.4 Grading stays in `aggregate`

Grading waits for the aggregate on purpose:

- A scorer bug must not spoil the collected row. The Candidate answer stays available for
  re-grading (`single_shot.py`, `/check` docstring).
- A judged scorer awaits model calls on the run's event loop (OME-1240,
  `grading_endpoints.py`). A code mount is awaited on the same loop.
- A whole-run metric (ContractEval F1) needs all cases.

## 4. Runtime facts (verified on `origin/main`, prototype 2026-10-20)

A toy node ran the §3.1 shape on `packages/url4` with no change: a data-route collection, the
slice, code mounts with named inputs, `$candidate` and `$index` deep in the body, packed context
lines, and collected error rows.

| Fact | Evidence | Consequence |
|---|---|---|
| F1 — `cases` is an endpoint, and an endpoint needs `q=`. | `url4/peer/_dispatch.py`, `case_selection.py` | `cases` becomes a data route (`node.data`, `application/json`). |
| F2 — The Engine mounts no code. | `url4/dag/nodes/code.py` `_code_port` | `case-evaluation`, `aggregate`, `aggregate/case-result`, `aggregate/graded` and `commit-prompt` become code mounts. |
| F3 — One path is one route. | `url4/peer/server.py` `_check_routable` | The old endpoints are removed (D5). |
| F4 — The slice is applied after the full fetch. | `url4/dag/nodes/iteration.py` | Memory does not change. The pushdown stays in `OME-1675`. |
| F5 — Client progress counts `RelUrlNode` spans named `/benchmarks/case-execution`. | `screamingface/_ui/evaluation_state.py` | It counts `CodeCallNode` spans whose path ends in `/case-evaluation`. |
| F6 — Engine activity reads the case position from the Candidate request. | `case_request.py`, `activity/observer.py` | The Candidate endpoint decodes the facts from the packed context. |
| F7 — The url4 collected-error shape is private. | `url4/dag/nodes/_shared.py` `_error_payload` | `url4` exports it, so `case-evaluation` writes the same shape. |

### 4.1 Failure codes across code steps (owner decision, 2026-10-20)

A failed code step is `intent_error`, permanent (C §13.6). url4 keeps the handler's own code
and permanence as the error's `cause` (`url4.core.errors.ErrorCause`), in the raised error, in
a collected row (`"cause": {code, retryable}`) and in the terminal frame (`ErrorInfo.cause`).
The Engine's report projection (`aggregation.public_error`), its run summary, and the
Client's termination error read the cause first. So the public failure code and retry advice
stay what the Benchmark declared (`benchmark_unavailable`, a retryable judge failure, …).
`aggregate/case-result` returns its `CaseFinalizationError` row instead of raising, because
`Scoring.finish` keys on that row's `kind`.

### 4.2 Other behavior notes

- **Cases validation.** The cases data route still refuses a booklet that is not an array of
  objects before inference (`benchmark_contract_error`). A data route cannot see the run's
  selection, so the retired "at least N rows" check now lives in the aggregate; a prepared
  bundle holds exactly its declared Cases (Case Digest at image build).
- **Client progress.** A Case counts as finished when its `case-evaluation` code call ends.
  A Case whose Candidate fails now counts as finished and failed; before, it was not counted.
- **Fair share.** Code calls are in process, so they take no fair-share I/O slot
  (`FairShareIOLayer` forwards the code port ungated, like url4's `BoundedIOLayer`).
- **Retired expressions.** A Candidate call that still carries `context_format` fails with a
  named "retired Candidate protocol" error.
- **Version skew.** New Client + old Engine and old Client + new Engine both run; only the
  live progress count reads 0 across the skew.

## 5. Changes

### 5.1 `url4-sdk` (`packages/url4`)

1. Export the collected-error payload builder (F7) as public API (`url4.dag.collected_error`).
2. `ErrorCause` on `Url4Error`, set by code calls; carried in collected rows and `ErrorInfo`.
3. `url4.literal` / `literal_value`; `Url4Node.has_data`.

### 5.2 `screamingface-engine`

1. `cases` is a data route for imported boards and MedXpertQA.
2. `case-evaluation` is a code mount. It reads `case`, `attempt_1..N` (and `reasoning` for
   MedXpertQA), runs the board's check record and case grade in process, and returns today's
   row. It keeps today's activity phases and case scope.
3. `aggregate` (imported) and `aggregate/case-result`, `aggregate/graded` (MedXpertQA) are code
   mounts. They read `evaluations` / `execution` and `selected` / `case_count` instead of the
   context and an intent string. Judged boards still grade on the run's loop.
4. `commit-prompt` (MedXpertQA) is a code mount.
5. `/benchmarks/candidate` takes the prompt from the intent and the facts and recipe from the
   packed context. `context_format=case-v1` is removed.
6. One builder renders §3.1 and §3.2. `build_evaluation_protocol`, `preserve_candidate_outcome`,
   `early_result`, `/check`, `/benchmarks/case-execution`, `/benchmarks/case-attempts` and the
   `cases()!'N'` handler are deleted.
7. `EVALUATION_PROTOCOL_REVISION` does not change, so no revision id moves (D5).

### 5.3 `client-sf` (`packages/screamingface`)

1. Linking inserts `candidate:0.0:'<recipe>'` as the first top-level source (§3.1).
2. Progress counts the per-case `case-evaluation` code calls (F5).

## 6. Decisions (owner, 2026-10-20)

| Id | Question | Decision |
|---|---|---|
| D1 | Scope | Imported boards (`_build`) **and** MedXpertQA. They are the only users of the shared serving spine. |
| D2 | How the deterministic steps run | URL4 code mounts (`node.code`), as R1 requires. |
| D3 | `cases` and the slice | A data route now. The pushdown stays in `OME-1675`. |
| D4 | Where the activity facts come from | Named, unweighted sources on the Candidate call (`case_id`, `case_index`, `case_count`, `recipe`). |
| D5 | Revision and old routes | Keep every revision id. Remove the old endpoints. A run queued with an old expression during the deploy fails with a clear error. |

## 7. Acceptance

1. No quoted intent in the rendered expressions is a label, a count or a projection (R7). No
   identity wrapper. No one-element iteration.
2. On the local kind cluster, with the seeded prod request cache, a 3-case ContractEval run
   gives the same per-case answers, per-case scores and headline F1 as `origin/main`.
3. The same run makes zero new model calls (all cache hits).
4. The Client progress bar and the Engine activity log count every finished Case (§4.2).
5. Revision ids of every imported board and MedXpertQA do not change.
6. Gates pass for `screamingface-engine`, `client-sf` and `url4-sdk`.

## 8. Out of scope

- Moving per-case scoring out of `aggregate` (§3.4).
- Native boards other than MedXpertQA. They do not use the shared serving spine.
- Slice pushdown and contract de-duplication (`OME-1675`).
