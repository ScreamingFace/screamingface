# Importing inspect_evals benchmarks — the spec

*2026-09-09 · `OME-1113` · executes on `OME-1115` (adapter plugin) and `OME-1116`
(importer). Fixes the architecture decided 2026-09-04 (decision comments on `OME-1097` /
`OME-1103`) as one buildable contract. It **consumes** the merged `grade_case` seam and
the envelope decisions — it never redefines them.*

**The whole idea in one sentence: inspect_evals benchmarks become rows in our catalogue —
our engine conducts every run; from inspect we import only the dead components (question
banks + grader functions), never its runner, CLI, or logs.**

Think of inspect_evals as a rival exam board that publishes its question banks and marking
schemes under MIT. We don't hire their invigilators or sit students in their exam hall —
we photocopy the question paper and the marking scheme once, file them in our own
catalogue, and run the exam in our hall under our rules: one url4 expression per run,
sealed envelopes, metered cost, our report card.

## Before / After

### Before

- Trigger: a dev picks up the adapter-plugin or importer ticket.
- Today: the architecture is decided but scattered across decision comments; each build
  ticket would re-derive the package boundary, the shim contract, and the revision
  formula from archaeology.
- Cost: two tickets each paying the same research bill; drift between their answers.

### After

- Same trigger.
- Now: this document is the single contract. `OME-1115` builds §3 (the adapter plugin)
  and §4 (grading route = check surface); `OME-1116` builds §5 (the importer). Both
  inherit §2 (what already exists) and §6 (identity + licensing) without re-deciding
  anything.
- Win: the build tickets execute a spec, and every acceptance bar here is numeric.

### Don't regress

- Engine conducts everything; the SDK never calls the AI Gateway; inspect code runs only
  inside one engine-side plugin package (core never imports it — registry wiring only).
- `expression_sha` pins the whole protocol; imported boards pin
  revision = sha(pinned package digest + case subset).
- Sealed envelope: grading material reaches only the grading route, never the Candidate.
- `cost_usd` comes from the gateway meter, never from $/token estimates.
- Leaderboard scores are never published from inspect's own logs or runner.

## 1 · What we take from inspect — and what we never take

| Take (MIT, importable) | Never take |
|---|---|
| Datasets (`Sample[]`) — snapshotted at import/prepare time | Their `eval()` runner / solver loop |
| Scorer functions — standalone async callables `(state, target) -> Score` | Their `.eval` log as a results source |
| Env declarations (digest-pinned compose images) — **Later**, as reference designs for the `environment` envelope kind | Their CLI / TUI / viewer |
| | Leaderboard scores from their runs (no `expression_sha`, no metered cost) |

**Three structural facts make the lift safe** (verified in source + the `.ua/` knowledge
graphs, 2026-09-04): their scorer has no binding to their runner; their evals never import
each other (importing one brings nothing else along); their runner's only model seam is a
single `generate()` call — so nothing of theirs needs to *run* for their components to be
meaningful in our DAG.

## 2 · The contract this spec consumes (already merged — pointers, not copies)

**Everything below builds on two seams that exist on `main` today; the source of truth is
the code, and this spec deliberately repeats none of its field lists.**

- **The `grade_case` seam** (`OME-1097`, merged):
  `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/scored.py` —
  `GradeRequest` in, `CaseGradeOutcome` out, through the `GradeCase` async callable. The
  hourglass-waist invariant is written on the type: plain serializable data only, no
  engine objects, no callbacks. The spine owns the whole marking room (roll call, row
  index, failure ladder, exam scorer); a board writes exactly one hook.
- **Kind-tagged payloads** (`OME-1103`, decision comment 2026-09-04):
  `spine/payloads.py`. Closed union of kinds — `text` today, `text+attachments` /
  `environment` later, `Sample`-isomorphic to inspect by design ("no fourth format"),
  which is what makes this importer near-identity. The spine never opens the envelope.
- **The benchmark declaration surface**: `benchmarks/definition.py` — `Benchmark`,
  `BenchmarkDeclaration` (failure policy + interaction, required, no defaults),
  `CheckSurface`. `benchmarks/deployment.py` — `BenchmarkRegistration`,
  `BenchmarkAssetBundle` (the prepare-time asset seam, `OME-925`).
- **The catalogue `origin` field** (`OME-1112`, sibling ticket): one registration-record
  addition, `origin: "screamingface" | "inspect_evals"`. This spec assumes it; it does
  not design it.

## 3 · The adapter plugin package (`OME-1115` builds this)

**One engine-side package carries every inspect dependency, and engine core never learns
its name.** The plugin is the sealed crate the photocopied marking schemes ship in: the
engine forklifts crates through one loading dock (the registry) and never opens them in
the core import graph.

### 3.1 Package boundary and dependency carriage

- **Import package:** `screamingface_engine_inspect` — a *top-level* package at
  `apps/screamingface-engine/src/screamingface_engine_inspect/`, deliberately **not**
  under `screamingface_engine.` so an accidental core import is impossible to write as a
  relative import and trivially greppable as an absolute one.
- **Dependencies:** a uv optional-dependency group in the engine's `pyproject.toml`:
  `inspect = ["inspect-ai==<X>", "inspect-evals==<Y>"]` — **exact `==` pins**, because
  §6's revision identity hashes the pinned package digest. The default engine install
  stays inspect-free; the benchmark image installs `.[inspect]`.
- **Wiring:** the plugin exposes its registrations through the registry seam, not an
  import: an entry point in the `screamingface_engine.benchmark_deployments` group (new,
  this ticket) resolving to an iterable of `BenchmarkRegistration`. Engine composition
  discovers the group at startup and extends `BUILTIN_DEPLOYMENT`'s registrations with
  whatever is installed. Extra absent → group empty → engine behaves byte-identically to
  today. **Core gains one generic discovery loop and zero knowledge of any plugin's
  name** (hexagonal rule: core defines the port, the plugin registers into it).

### 3.2 The scorer shim — their marking scheme, our marking room

Their scorer protocol is one async callable: `(state: TaskState, target: Target) ->
Score`. Ours is `GradeCase`. The shim is a translator written once, with **zero
per-scorer branches** — the seam's honesty proof:

```python
def inspect_grade_case(scorer: Scorer) -> GradeCase:
    """Wrap one inspect scorer as a board's grade_case hook.

    Stage 1 — unpack our envelope: GradeRequest.input / .answer are kind-tagged
              payloads; only kind="text" is legal today (see §7 scope).
    Stage 2 — build the minimal TaskState: input_text from the case input,
              output.completion from the candidate answer; Target from
              GradeRequest.material (the imported Sample's target, carried as this
              board's per-case grading material).
    Stage 3 — await scorer(state, target); their Score comes back.
    Stage 4 — translate: Score.value (CORRECT/INCORRECT/float) -> CaseGradeOutcome.score;
              Score.answer/explanation/metadata -> the checks evidence block, preserving
              the judge's own words; scorer exceptions / unmappable values -> a named
              failure code, never a silent drop.
    """
```

Failure codes the shim owns (wording is plugin voice, per the spine's byte-identical
rule): `scorer_error` (the scorer raised), `invalid_score_value` (a `Score` we cannot map
to a float). Everything upstream (missing row, case error, refusal) is spine ladder
territory — the shim never re-implements it.

**If any of the ~94 single-shot scorers needs a special-case branch inside the shim, the
seam failed review** — same bar the `OME-1097` signature carried.

### 3.3 Judge routing — zero code

Model-graded scorers resolve their judge through inspect's own provider machinery. **We
route it with configuration, not code:** the plugin runs those scorers with inspect's
`openai-api` provider pointed at our AI Gateway via base-URL + key environment variables
in the engine's runtime (the gateway speaks the OpenAI surface). Consequences, all free:
judge calls are metered like every other gateway call (so `cost_usd` stays the meter's
number), rate-limited and logged under our roof, and the judge model is pinned by our
configuration — never by a default buried in their eval.

## 4 · Grading route = check surface (the load-bearing move)

**The wrapped scorer is registered twice under one identity: as the board's grading route
and as its `CheckSurface.check_route`.** Same examiner, two office hours — after the exam
(grading) and during it (feedback). This single move is why every protocol we have —
fusion, corrective_loop, anything future — works on imported boards with **zero adapter
changes**: protocols live in the url4 DAG the client compiles; the benchmark only ever
answers "grade this / give feedback".

Existing pattern to copy, not invent: healthbench installs its check-surface route beside
its grading route from one definition (`benchmarks/healthbench/exam.py`,
`benchmarks/rubric_check.py`). The plugin does the same through `Benchmark.install`.

One deliberate exception carried over from `OME-796`: **MCQ-style boards get no check
surface** — pass/fail feedback over a handful of options is an elimination attack, and
the client preflight's refusal of a loop recipe there is correct behavior, not a gap. The
importer decides per board (§5) whether a check surface is declared.

## 5 · The importer (`OME-1116` builds this)

**One inspect Task in → one SF manifest out, ≤150 lines of per-board code.** The importer
is a per-board authoring session made mechanical, not a runtime component: it runs at
import/prepare time and leaves behind only dead data plus one small module.

Per eval, the importer:

1. **Loads the Task** from the pinned `inspect-evals` package and takes exactly two
   things: `task.dataset` and `task.scorer`.
2. **Snapshots the dataset** through the existing `BenchmarkAssetBundle.prepare` seam:
   `Sample` rows are materialized to an immutable asset file at image build time — HF
   downloads happen once, then never again. Upstream gating or drift cannot change a
   published board (`OME-925` auditability holds).
3. **Renders the prompt as data.** We import no solver — but single-shot evals' solver
   chains do prompt formatting (templates, MCQ choice lists). The importer bakes that
   formatting into each case's `text` payload at import time, reproducing the solver
   chain's prompt as a string. This is the per-board hand-work inside the 150-line
   budget.
4. **Carries `Sample.target` as the board's per-case grading material** — the exact
   value §3.2's shim hands back to the scorer.
5. **Authors the `Benchmark`**: id per §6; the standard single-shot url4 protocol via the
   existing builders (`definition.py` `candidate(...)` + the spine); an explicit
   `BenchmarkDeclaration` — **failure policy and interaction declared per board, no
   defaults** (`OME-1039` rule, unchanged); `origin="inspect_evals"`; a check surface iff
   §4 allows one; `dataset_url` + license note per §6.
6. **Registers** the result in the plugin's entry-point deployment (§3.1).

## 6 · Identity, snapshots, licenses

- **Benchmark id is flat**: `inspect-<name>` (e.g. `inspect-mmlu`) — the registry's id
  charset has no `/`, and identities stay flat (`OME-836`). Grouping is the `origin`
  field's job (`OME-1112`); whether the SDK also accepts an `inspect/mmlu` spelling is
  `OME-1114`'s call, not a second identity.
- **Revision identity**: `revision = sha256(pinned inspect-evals package digest + the
  imported case-id subset)`, hex, within the 64-char display limit. Change the pin or the
  subset → a new revision → recorded submissions stay comparable. The dataset snapshot's
  own digest lands in the asset-prepare summary for audit, but editorial fields never
  enter `revision` (existing `definition.py` invariant).
- **License gate before the leaderboard**: the code is MIT; the *datasets* are not
  uniformly. Per board, the importer records the dataset license in the manifest
  (`dataset_url` + license note), and **only license-cleared datasets go on the public
  catalogue** — a gated or unclear dataset stays off it, with the refusal written in the
  board's import module rather than discovered at deploy time.

## 7 · Scope

- **Now:** the ~94 single-shot QA evals — `text` envelope, programmatic + model-graded
  scorers. `OME-1115` proves one board end to end; `OME-1116` lands the importer + ten.
- **Later:** 13 execution-graded evals (sandbox for the *grading step* only); 35 agentic
  evals (ride the `environment` envelope kind, `OME-1103`); report export in inspect's
  log format (`OME-1117`). Their compose declarations ship as reference designs for our
  sandbox runner, nothing more.
- **Out (on purpose):** running anything under inspect's own loop — the loop is part of
  what a leaderboard score measures, and a scaffold `expression_sha` cannot pin must not
  exist; publishing scores from inspect logs — no expression hash, no metered cost, no
  audit trail; a `@modelapi` wrapper making our fusion callable from their CLI — a
  possible future distribution/oracle tool, but nothing here depends on it.

## 8 · Acceptance (numeric, falsifiable)

1. `sf.evaluate(fusion, benchmark="inspect-mmlu", limit=50)` completes with the full
   report widget, indistinguishable in shape from a draco run — per-member usage, failure
   stage+code, grade evidence, metered `cost_usd`.
2. ≥10 single-shot evals imported at **≤150 lines each**, with **zero spine edits** and
   **zero per-scorer branches in the shim**.
3. A corrective_loop completes on ≥1 imported board via the scorer-as-check-surface.
4. `uv sync` without the `inspect` extra installs no inspect distribution, and
   `grep -r "screamingface_engine_inspect" src/screamingface_engine/` inside engine core
   returns nothing.
5. Reported cost matches the gateway meter exactly (it **is** the meter, passed through).
