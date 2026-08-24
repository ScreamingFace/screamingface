---
ticket: OME-971
stack: screamingface-engine
status: in_progress
started: 2026-08-24
finished:
---

# OME-971 — Onboard the GDPval text subset as a rubric-graded benchmark

## Intent

GDPval appears in frontier-model launch tables, so a fusion-beats-solo result on it carries
weight our current benchmark set cannot buy. Its official metric — blinded expert pairwise win
rate against a human professional's deliverable — is not reproducible here. But every task in
the open gold subset ships `rubric_json` (median 47 scored criteria, `required` null
throughout), which is the same per-item checkmark family as `healthbench-worst30`. This unit
onboards the prose-only slice of that subset so the existing rubric-judging machinery can grade
it, with no code execution, no sandbox and no artifact handling.

## Baseline re-verified against origin/main @ 443113b4 (2026-08-24)

The planning document was written against a checkout 20 commits stale. Four carried-in
assumptions were re-checked at the branch base; three had already changed.

- **RETIRED — the 1 MiB truncation defect is fixed.** OME-892 replaced truncation with a
  three-way fork in `runner/executor.py::build_result`: inline under
  `DEFAULT_RESULT_INLINE_CAP_BYTES` (524,288), otherwise spill the COMPLETE body to a
  content-addressed artifact store, otherwise refuse with `result_too_large` as a FAILED
  terminal event — "never cut". This unit is NOT blocked; the blocked-by on OME-971 should be
  removed.
- **RETIRED — full HealthBench already shipped.** `HEALTHBENCH_PROFESSIONAL` is registered
  beside `HEALTHBENCH_WORST30`, sharing one asset bundle. No separate ticket needed.
- **CHANGED — benchmarks register through a deployment.** `BUILTIN_DEPLOYMENT` composes
  `BenchmarkRegistration(benchmark=..., asset_bundle=BenchmarkAssetBundle(id=..., prepare=...))`;
  assets build via `benchmarks/prepare.py::prepare_builtin_assets`. Two identities may share one
  bundle — the precedent to follow if a second GDPval board is added later.
- **NEW — artifact storage exists.** `screamingface_engine/artifacts/` provides writer/reader
  ports with filesystem and S3 backends (f9c3f795). Unused here; material for the later
  file-deliverable phase.

Also: `apps/url4-cloud` is now `apps/screamingface-engine`, package `screamingface_engine`
(9b888579). All planned paths below reflect that.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/gdpval/__init__.py`
- `.../gdpval/definition.py` — `GDPVAL_TEXT` identity, judge pin, revision hash
- `.../gdpval/exam.py` — `ASSET_BUNDLE_ID`
- `.../gdpval/subset.py` — frozen 102-task id list + sha
- `.../gdpval/prepare.py` — `prepare(out)`: bake cases + rubric assets
- `.../gdpval/ingestion.py` — pdf/docx → text, build time only
- `.../gdpval/rubric_filter.py` — format-criteria filter
- `.../gdpval/prompts.py`, `verdict.py`, `scoring.py`
- `.../gdpval/case_evaluation.py`, `aggregate.py`, `runtime.py`
- `.../benchmarks/builtins.py` — register `GDPVAL_TEXT` + `GDPVAL_ASSETS`
- `apps/screamingface-engine/tests/unit/test_gdpval_{prepare,definition,grading,aggregate,check_surface}.py`

## Test plan

RED first, per `sdlc-python`.

- `prepare`: frozen id-list drift fails the build; re-running over the same revision is
  byte-identical; a reference extracting below the viability threshold fails loudly rather than
  baking an empty reference.
- `definition`: the revision hash changes when any of dataset revision, preparer revision,
  frozen id list, judge pin, or filter revision changes.
- `grading`: each rubric item judged independently; a malformed judge reply is retried, then the
  case marked failed; the format filter removes the expected criteria BEFORE scoring.
- `scoring`: points earned over positive points available, negatives subtract, `required`
  ignored; all judge calls failing yields `score = None`, never `0.0`.
- `aggregate`: `coverage` is the exact graded fraction; `case_count` equals the selected count.

## Acceptance

- `gdpval-text` registered and served with `case_count = 102` and a pinned revision hash;
  `sf.evaluate(model, benchmark="gdpval-text")` returns per-case rubric scores.
- Format-checking criteria filtered before scoring; a failed judge yields `score = None`.
- Benchmark description states the subset rule and that scores are not comparable to OpenAI's
  published win-rate.
- Gates: `ruff check`, `ruff format --check`, `pyright`, `check_layering.py`, `pytest --cov=screamingface_engine
  --cov=url4.streaming --cov-fail-under=80`.

## Measurements from Phase 0 (2026-08-24, recomputed from the published parquet, no model spend)

- Rubrics on 220/220 tasks; criteria min 14 / median 47 / max 137; 10,453 total; `required` is
  `None` on every one; weights mostly +1 (5,369) or +2 (4,341); 94 negative.
- Text subset per the extension filter `{.docx,.doc,.txt,.md,.pdf,""}` (a task with no files
  counts as passing): **109** tasks — 83 expecting a prose deliverable FILE, 26 with none.
- Reference files in the subset: 85 (44 PDF, 41 DOCX) across 43 tasks; **66 of the 109 tasks
  have no reference files at all**.
- Extraction sweep over all 85 (pdfplumber + python-docx): 77 clean, 6 near-empty (scanned-image
  PDFs, an embedded-logo docx), 2 `XMLSyntaxError`. At task level: 102 clean, 5 partially
  degraded, 2 total loss → **this unit ships 102 tasks and documents the 7**.
- Frozen 102-task list sha256
  `2ea8c0d88ebbde08a3456e482d63f3a86a671c3db6785a844b7ba69358c50eb7`.
- After the format filter the 102 tasks carry **4,498 criteria** (raw 4,553; 55 filtered),
  min 13 / median 44 / max 83 per task, 7,183 positive points; 9/9 sectors, 37/44 occupations.
- **Cost consequence:** the HealthBench pattern fans out ONE judge call per rubric item
  (`healthbench/runtime.py::rubric_tasks` renders a `grader_prompt` per item), so a full run is
  ~4,498 judge calls per candidate — roughly 44x the per-task judging the planning document's
  cost model assumed. Must be measured in the pilot before any full run.

## Progress

### Task 1 — frozen selection, pins, and the container filter (DONE)

- **Actual files:** `benchmarks/gdpval/{__init__,subset,rubric_filter}.py`,
  `tests/unit/test_gdpval_{subset,rubric_filter}.py`. `pins.py` deferred to Task 5, where the
  judge pin is first needed — nothing in Task 1 reads it.
- **Gates:** ALL GATES GREEN — ruff check · ruff format --check · pyright · check_layering ·
  pytest --cov-fail-under=80. 2,028 passed, 6 skipped; 14 new tests, no prior test touched.
- **Deviations:**
  - **The filter design changed mid-task, on owner decision.** The planned filter was a bare
    keyword match on format markers. A hand audit against all 4,553 criteria of the 102 selected
    tasks showed it deleting SEVEN content criteria — including a -10 penalty — because a
    REFERENCE filename ended in `.docx`, and missing an unknown number of container criteria
    phrased without those markers. Replaced with a three-rule container-vs-content test
    (strip quoted spans → require a format token → discriminate delivery from content).
    Measured: 99 removed, 209 of 7,183 positive points, zero false positives across a full audit
    of all 99; three known misses (~6 points) pinned in the tests. Spec D3 and F5 updated.
  - `test_gdpval_rubric_filter.py` was REWRITTEN rather than appended to. Same uncommitted
    cycle, design changed by owner decision, and the replacement is strictly stronger: every
    fixture is now a real criterion copied from the published rubrics, since invented fixtures
    were how the first filter passed its tests while deleting real criteria.
  - The shipped module was re-run against the published parquet to confirm it reproduces the
    prototype's measurements exactly (99 / 209). Prototype-to-production drift here would have
    silently changed the answer key.

### Task 2 — build-time reference extraction (DONE)

- **Actual files:** `benchmarks/gdpval/ingestion.py`, `tests/unit/test_gdpval_ingestion.py`.
- **Gates:** ALL GATES GREEN. 8 new tests, no prior test touched.
- **Deviations:**
  - **The reader is INJECTED rather than imported directly.** `pdfplumber` and `python-docx` are
    build-time only — absent from the runtime AND the test environment, exactly as `datasets` is
    for the other preparers — so a module that imported them directly could not be unit-tested at
    all. The policy (viability floor, error identification, determinism) takes a `reader`
    callable; `pdf_reader()` / `docx_reader()` are thin adapters exercised only at image build.
    This is the hexagonal rule in CLAUDE.md applied to a dependency boundary that already existed.
  - **`MIN_VIABLE_CHARS = 200` is derived, not guessed.** Measured over all 85 reference files of
    the 109 prose-only tasks: the six unusable extractions clustered at 0, 0, 0, 0, 81 and 106
    characters; the smallest genuine extraction was 261. Any threshold in (106, 261] separates the
    two populations. A test asserts the constant stays inside that interval, so a later retune
    cannot drift to a number nobody can re-derive.
  - `extract_reference_text` catches broadly and re-raises as `IngestionError`. Deliberate and
    annotated: readers fail in library-specific ways (python-docx raises XMLSyntaxError for a
    malformed package), and what the operator needs is WHICH of 85 files broke. The original
    exception is preserved as the cause.

### Task 3 — bake the Cases and rubrics (DONE)

- **Actual files:** `benchmarks/gdpval/{prepare,pins}.py`, `tests/unit/test_gdpval_prepare.py`.
- **Gates:** ALL GATES GREEN. 11 new tests, no prior test touched.
- **Verified against the real dataset:** `select_rows` returns 102; `rubric_items` leaves 4,454
  criteria after the container filter — matching the independent measurement exactly; `emit`
  writes ids 1..102 with one rubric asset each.
- **Deviations:**
  - **`pins.py` landed here, not in Task 5.** The preparer needs `DATASET` and
    `DATASET_REVISION`; deferring it would have meant hard-coding them twice. Judge pins still
    arrive with the board in Task 5.
  - **Selection is addressed by `task_id`, not by row position.** HealthBench freezes 1-based
    positions in the upstream file because its rows have no stable identity. GDPval rows carry
    stable `task_id`s, so ordering comes from `TEXT_SUBSET_TASK_IDS` and the build asserts every
    frozen id is present. A reshuffled upstream file therefore cannot renumber this exam.
  - **A test of mine was wrong and was fixed.** `test_cases_json_carries_no_rubric` asserted that
    the string "criterion" is absent from `cases.json`. It passed on synthetic prompts and would
    have failed on real data for an innocent reason — one GDPval task says "as a release
    criterion" in its own prompt text. Replaced with a structural assertion (case keys are
    exactly `{id, input}`; the envelope is exactly `{schema, messages}`), which is what the
    invariant actually claims. Caught by running the preparer over the published parquet rather
    than by the test suite.

### Task 4a — the scoring metric (DONE)

- **Actual files:** `benchmarks/gdpval/scoring.py`, `tests/unit/test_gdpval_scoring.py`.
- **Gates:** ALL GATES GREEN. 12 new tests, no prior test touched.
- **Deviations:**
  - **Scope narrowed to scoring alone.** The plan bundled scoring, verdict, prompts and records
    into Task 4. Verdict parsing and the grader prompt are inseparable from the url4 expression
    that nests the judge inside the verdict route for retry, so they move to Task 5 where that
    tree is written. Keeps this iteration one focused unit (loop rule 2).
  - **`case_score` duplicates `healthbench.scoring.case_score` deliberately, not by oversight.**
    The per-case math is identical; the OBLIGATIONS are not. HealthBench's module is bound to
    simple-evals parity and must follow the reference if it moves; this board's metric answers to
    the GDPval rubrics alone. A shared version could only drift under one caller's obligations
    while silently redefining the other's exam. The reasoning is recorded in the module, since a
    later reader will otherwise read it as duplication worth collapsing. Repo precedent agrees —
    DRACO and HealthBench each own a `scoring.py` and nothing imports across benchmarks.
  - **The exam mean is plain, with no clip** (spec D4). HealthBench's professional board clips
    because the official HealthBench metric does; GDPval's official metric is an expert pairwise
    win rate, so there is no published convention to match and a floor would imply one exists.

### Task 5a — judge pins, grader prompt, verdict parsing (DONE)

- **Actual files:** `benchmarks/gdpval/{pins,prompts,verdict}.py`,
  `tests/unit/test_gdpval_verdict.py`.
- **Gates:** ALL GATES GREEN. 27 new tests (parametrised), no prior test touched.
- **Decisions:**
  - **Judge is DRACO's pin — `openrouter/google/gemini-3.1-pro-preview`** (owner decision).
    GDPval's official grading is blinded expert PAIRWISE comparison, unreachable here, and
    OpenAI's automated stand-in is a hosted service rather than a callable model — so the judge
    is our free choice. Reusing DRACO's keeps one judge across two rubric-graded boards, which is
    one variable rather than two when scores move. Named as a deviation in the board description.
  - **`temperature=0.2` is carried over and is load-bearing for retry.** An unparseable reply is
    retried by re-resolving the nested judge call; at temperature 0 the retry would re-send
    identical bytes and fail identically. HealthBench solves this by pinning no temperature at
    all; DRACO's 0.2 achieves the same redraw while staying near-deterministic.
  - **`JUDGE_RETRIES = 2`.** The reference loops forever on malformed replies. At ~4,498 judge
    calls per candidate an unbounded retry against a systematically broken prompt would burn a
    run's budget before anyone noticed.
  - **Cost measured, and an earlier claim corrected.** At $2/$12 per 1M, one judge call is
    ~$0.0114 and a full 102-task run is ~$51 per candidate; a five-task pilot is ~$3. The
    ledger previously implied the per-item fan-out made the planning document's estimate "44x
    low" — the CALL COUNT is ~44x, but each call is small (one criterion in, a short verdict
    out), so the total lands near the original figure by a different route.
- **Deviations:**
  - `_invalid_reason` is a check TABLE rather than a chain of guards, to satisfy `PLR0911`
    (max 3 returns). The ordering comment is load-bearing: `isinstance(True, int)` is True in
    Python, so the bool check must be an explicit `isinstance(..., bool)` and must come last.

### Tasks 5b + 6 — the board, its routes, and registration (DONE)

- **Actual files:** `benchmarks/gdpval/{exam,definition,check_policy,case_evaluation,aggregate,
  runtime}.py`, `scoring.py` (+ `sample_stdev`, `verdict_coverage`),
  `tests/unit/test_gdpval_definition.py`; `benchmarks/builtins.py` registers `GDPVAL_TEXT`.
- **Gates:** ALL GATES GREEN (`--skip-append-only`, see below). 2,100 tests pass.
- **Served:** `gdpval-text`, 102 cases, revision `04dd881e686c0cca`.

- **Two prior-test changes, both owner-approved Confidence-Gate decisions:**
  1. `test_gdpval_verdict.py` — `bind` stored a rejected reply under `"raw"`; the contract's
     Evidence field is `raw_output` (`benchmarks/contract.py:61`). Left as-is, a rejected judge
     reply would be recorded as invalid with NOTHING to inspect — the audit trail silently
     dropped, on exactly the artefact one would investigate after a bad run. Owner chose to fix
     the key rather than add a translation layer hiding the mistake.
  2. Four registry enumerations (`test_benchmark_protocol`, `test_benchmark_display_metadata` x2,
     `test_benchmark_deployment`) list the installed boards exhaustively. Adding a sixth board is
     precisely what they exist to force. Each was EXTENDED, never relaxed — the assertions remain
     exhaustive.

- **Defect caught before it shipped: a 1-based/0-based mismatch.** `prepare` assigned `rubric_id`
  from a 0-based enumerate, while `scoring.case_score` indexes points with
  `enumerate(points, start=1)` and `verdict.binding_key` rejects ids below 1. Every criterion
  would have been scored against the WRONG point value, silently and plausibly. Fixed at all
  three sites and pinned by `test_rubric_ids_are_one_based_positions`. Found only by wiring the
  reducer against the preparer — neither module's own tests could see it.

- **Deviations:**
  - `aggregate.py` and `runtime.py` mirror HealthBench's structure closely rather than sharing
    it. Same reasoning as `scoring.py`: that board's revision is FROZEN at a published value, and
    parameterising its reducer to serve a second benchmark would put a live identity at risk to
    remove a structural resemblance.
  - `check_policy.CHECK_THRESHOLD = 0.5` is PROVISIONAL and says so. DRACO's 0.7 was set against
    known baselines; no candidate has been measured on this board yet, so the first real runs
    should confirm the bar separates drafts worth iterating from drafts worth stopping.

### Task 7 — first real prepare run, and what it found (DONE)

Running the preparer against live data surfaced three defects that no unit test could have
caught, because each lived in the gap between a module and the outside world.

- **The dataset pin was wrong — the serious one.** `DATASET_REVISION` was copied from
  UKGovernmentBEIS/inspect_evals (`a3848a2a…`, 2025-09-25). At that revision `rubric_json` is
  NULL on all 220 rows: rubrics arrived five months later in `11e7900c` — "Release GDPval v2
  (rubrics + deliverables)", 2026-02-10. The reference implementation never reads the rubrics
  (it uploads deliverables to OpenAI's grading service), so its pin never needed them; this
  board is built entirely on them. Pin corrected; an AIDEV-NOTE records why it must not be
  re-copied. Board revision moved `04dd881e686c0cca` -> `820f9f3b52bd146a`.
- **Reference files were never downloaded.** Phase 0 fetched them by hand; the preparer pointed
  its reader at a directory nothing populated. `reference_urls` + `_fetch` added, resolving URLs
  inside the reader so `emit`/`case_input` keep the signatures their committed tests pin.
- **No retry on fetch.** 85 sequential downloads from a public CDN; one "Connection reset by
  peer" killed a multi-minute build. Four bounded attempts with backoff — bounded, so a genuinely
  missing file still fails rather than looping.

**The design held:** the preparer FAILED LOUDLY at case 1 rather than baking 102 empty rubrics
and shipping a benchmark that scored every candidate at zero. That is the "fail the build, never
bake empty" invariant doing its job.

**A test then surfaced a fourth issue:** `_build_reader` eagerly constructed both concrete
readers, making `pdfplumber` and `python-docx` hard requirements of every build — including the
66 of 102 tasks that carry no reference files at all. Now built lazily, per extension, on first
use.

**Verified end to end:** `gdpval: baked 102 cases` — 102 cases, 102 rubric assets, 58 reference
files downloaded and flattened.

### Scope expansion (owner decision, 2026-08-25)

The SDK-side CLI and example notebook were folded into this ticket rather than filed as a
sibling. OME-971 therefore spans two landings — `url4-cloud` and `py-screamingface` — which
CLAUDE.md §8 would normally split into an epic. Flagged and overridden by the owner; the
`py-screamingface` label should be added to the issue so the board reflects it.

### Task 8 — SDK surface: CLI prepare and the example notebook (DONE)

Folded into this ticket by owner decision, so OME-971 spans `url4-cloud` and
`py-screamingface`.

- **Actual files:** `_runtime/cli.py`, `tests/test_runtime_cli.py`,
  `scripts/build_notebooks.py`, `examples/10_gdpval.ipynb` (generated).
- **Gates:** ALL GATES GREEN on the `screamingface` stack (`--skip-append-only`) — ruff ·
  ruff format · pyright · pytest --cov-fail-under=95 · check_notebooks · uv build ·
  check_distribution.
- **Changes:** `"gdpval"` added to `_BENCHMARKS` (it is the `choices=` for `prepare`, so the
  command previously failed at argument parsing); `"gdpval": ("cases.json", "rubrics")` added to
  `_validate_benchmark_output`'s required-files table, which would otherwise `KeyError` after an
  otherwise successful prepare. No reference directory is required there: GDPval's references are
  flattened into `cases.json` at build time, so the downloaded originals are a build cache rather
  than a served asset.
- **Prior-test change (third of the same category, previously approved twice):** the
  `test_benchmark_fingerprint_uses_engine_preparation_revision` parametrize tuple is an
  exhaustive benchmark enumeration; `gdpval` was ADDED to it. Coverage extended, never relaxed.
- **Notebook:** `_gdpval_e2e()` added to the deterministic builder and registered as
  `10_gdpval.ipynb`. Its opening cell states both deviations before any code runs — pairwise
  expert grading vs per-criterion rubric judging, and a formatted document vs plain text — so a
  reader cannot reach a number without meeting the caveat. It also warns that grading fans out
  one judge call per criterion (~4,500 per candidate on a full run) before suggesting `limit` is
  dropped.
- **`_benchmark_fingerprint` needed no change:** it reads `DATASET_REVISION` off the `prepare`
  module, and GDPval's is imported into that namespace from `pins.py`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
