# OME-971 — The GDPval text subset as a rubric-graded benchmark

**Ticket:** [OME-971](https://linear.app/openmined/issue/OME-971/onboard-the-gdpval-text-subset-as-a-rubric-graded-benchmark)
· **Ledger:** `docs/work/2026-08-24-OME-971-gdpval-text-subset.md`
· **Stack:** screamingface-engine · **Date:** 2026-08-24

## 1. Problem

GDPval (arXiv:2510.04374) evaluates models on real professional work: 44 occupations across the
nine largest sectors of US GDP, tasks authored by professionals averaging 14 years of
experience. It appears in frontier-model launch tables. We serve no benchmark of that kind.

Its official metric is unreachable. Grading the 220-task open gold subset was done by blinded
expert pairwise comparison against a human professional's deliverable, at over an hour per
comparison; OpenAI's own automated stand-in reaches 66% agreement with those experts, against
71% human inter-rater agreement. Neither is something this Engine can run.

But the published gold subset ships something the paper barely mentions: `rubric_json`, a list
of scored criteria on **220 of 220** tasks — 10,453 criteria, median 47 per task, `required`
null on every one. That is the same per-item checkmark family as HealthBench, where our
existing judge chain already works.

The obstacle is that GDPval is a document-production benchmark. Of its 248 deliverable files,
231 (93%) are PDF, Word, Excel or PowerPoint. Producing and grading those artifacts is a
separate programme. This unit takes the slice that does not need them.

## 2. Established facts

Recomputed from the published parquet on 2026-08-24 — all 220 rows, not sampled. Engine facts
verified at branch base `443113b4`.

- **F1 — every task has a rubric.** 220/220; 10,453 criteria; min 14 / median 47 / max 137;
  `required` is `None` on all 10,453; weights are mostly +1 (5,369) or +2 (4,341), with 94
  negative criteria spanning -1 to -85.
- **F2 — the text subset is 109 tasks** under the extension filter
  `{.docx,.doc,.txt,.md,.pdf,""}`, where a task listing no files counts as passing. 83 of those
  expect a prose deliverable FILE; 26 list no deliverable file at all.
- **F3 — parsing is a bounded job.** 66 of the 109 have no reference files. The other 43 carry
  85 files: 44 PDF, 41 DOCX. No spreadsheets — the filter excludes them.
- **F4 — seven tasks have unusable references.** Extracting all 85 files with pdfplumber and
  python-docx: 77 clean, 6 near-empty (scanned-image PDFs such as `BOB 1099-INT.pdf`, an
  embedded-logo docx), 2 `XMLSyntaxError`. At task level: 102 clean, 5 partially degraded,
  2 total loss.
- **F5 — container criteria are a measurable tax.** Criteria that judge the delivered FILE
  rather than the answer's content — "provided as a Microsoft Word (.docx) document", "A single
  PDF file is delivered" — are unearnable by a text answer. Across the 4,553 criteria of the 102
  selected tasks there are **99**, worth **209 of 7,183 positive points (2.9%)**.
- **F6 — the subset stays broad.** 9/9 sectors, 37/44 occupations; rubric size min 13 /
  median 44 / max 83 after filtering — the 137-criterion worst case is not in scope.
- **F7 — judging fans out per rubric item.** `healthbench/runtime.py::rubric_tasks` renders one
  `grader_prompt` per criterion. Over 102 tasks that is ~4,498 judge calls per candidate.
- **F8 — boards are built from an exam template.** `healthbench/exam.py::healthbench_benchmark`
  takes `case_ids`, `mean` and `id` and derives revision, routes and the url4 tree; two boards
  already share one asset bundle via `BUILTIN_DEPLOYMENT`.
- **F9 — results are no longer truncated.** OME-892's `build_result` is inline / spill-whole /
  refuse-with-`result_too_large`. The 1 MiB failure that motivated the original blocked-by no
  longer exists.

## 3. Decisions

- **D1 — one board, `gdpval-text`, serving 102 cases.** The 7 tasks from F4 are excluded, not
  shipped-and-flagged: a task whose references failed to extract produces a low score that reads
  as model weakness, which is the failure mode this unit most needs to avoid.
- **D2 — reference text is baked at build time.** A Runner Job has no network egress and a
  read-only disk, so extraction cannot happen at run time. Parsed once at dataset creation, every
  model and fusion consumes byte-identical inputs.
- **D3 — container criteria are filtered in `prepare`, not at grading**, by a three-rule
  container-vs-content test whose revision is hashed into the exam revision:

  1. Strip quoted spans before matching. A filename inside quotes is a REFERENCE the answer must
     be consistent with, not a demand about the deliverable's own format.
  2. Require a format token — an extension, "Word document/file", "Excel workbook",
     "PDF file/format", "filename", "basename". Necessary, never sufficient.
  3. Discriminate on the assertion. A container criterion asserts the ACT OF DELIVERY
     ("provided", "delivered", "submitted", "deliverable is", "attached"); a content criterion
     asserts what is INSIDE ("contains", "includes", "shows", "lists"). Content phrasing wins
     unless the criterion ALSO asserts delivery.

  Measured: 99 removed, 209 positive points, zero false positives across a full hand audit of
  all 99. Three known misses remain (~6 points, 0.08%), pinned in the tests as accepted residual.

  **WHY the asymmetry matters.** Over-removal shrinks the denominator and inflates every
  candidate's score; under-removal penalises every candidate equally and stays visible in the
  number. A bare keyword version of this filter was written first and deleted seven CONTENT
  criteria — including a -10 penalty — because a reference filename ended in `.docx`. Rule 1
  exists for that. When in doubt, keep the criterion.

  Considered and rejected: not filtering at all. The handicap is identical across candidates and
  so preserves ranking, but 2.9% is large enough to matter when a fusion is compared against a
  strong solo model, and the audited filter carries no measured false-positive risk.
- **D4 — scoring is `rubric-mean-v1`.** Per case: points earned over positive points available,
  negatives subtracting, unclamped. Exam: the plain mean. No clip — the official GDPval metric is
  a win rate, so there is no published convention to line up with, and inventing a clip would
  imply one.
- **D5 — the selection fingerprint is taken over GDPval `task_id`s**, not Engine case ids: this
  board's identity IS a selection out of 220, so the dataset's own stable ids are the honest
  fingerprint. (HealthBench worst30 does the same with HF row ids.)
- **D6 — judging mirrors HealthBench**: one judge call per criterion, pinned model, retry on an
  unparseable reply. Named as a deviation from GDPval's official grading in the description.

## 4. Design

New package `benchmarks/gdpval/`, mirroring HealthBench's split:

| Module | Responsibility |
|---|---|
| `pins.py` | dataset + revision, judge model/params/retries, preparer revision, filter revision |
| `subset.py` | frozen 102 `task_id`s + `subset_sha()`; the exclusion list with its reason |
| `ingestion.py` | pdf/docx → text; build time only; viability threshold |
| `rubric_filter.py` | the format-criteria predicate + its revision string |
| `prepare.py` | `prepare(out)` → `cases.json`, `rubrics/<case>.json` |
| `exam.py` | `gdpval_benchmark(...)` → `(Exam, Benchmark)`; revision, routes, url4 tree |
| `definition.py` | the `gdpval-text` board — one call to `gdpval_benchmark` |
| `prompts.py` / `verdict.py` / `scoring.py` / `records.py` | grader template, reply parsing, point sum, record binding |
| `runtime.py` / `case_evaluation.py` / `aggregate.py` / `check_policy.py` | the six protocol routes |

Registration adds one `BenchmarkRegistration(benchmark=GDPVAL_TEXT, asset_bundle=GDPVAL_ASSETS)`
to `BUILTIN_DEPLOYMENT`, with `GDPVAL_ASSETS` carrying a lazy `prepare` import as DRACO and
IFEval already do.

**Case input.** One case is the task `prompt`, followed by the extracted text of its reference
files under a stable delimiter, in the dataset's file order. Engine case ids are the 1-based
positions `prepare` numbers by, matching HealthBench.

**Exam revision** hashes: dataset revision, preparer revision, filter revision, protocol
revision, scoring name, and the selection sha. Any change re-addresses every route.

## 5. Error handling

- A reference whose extracted text falls below the viability threshold **fails the build**,
  naming the task and file. It never bakes an empty reference.
- The frozen id list is asserted against the pinned dataset at build time; drift fails loudly,
  as HealthBench's `WORST30_CASE_IDS` assertion does.
- An unparseable judge reply is retried per `JUDGE_RETRIES`; still unparseable, the case is
  marked **failed** with a named failure.
- A case with no numeric grade yields `score = None` and contributes nothing to coverage. The
  `CandidateResult` contract already forbids turning infrastructure failure into a plausible
  zero; this unit inherits it rather than restating it.

## 6. Consequences

- **Cost is judge-dominated.** ~4,498 judge calls per candidate for a full run (F7). The
  planning document's estimate assumed one judge pass per task and is therefore low by roughly
  44x on the judging term. A five-task pilot (~220 judge calls) must measure real cost before
  any full run is scheduled.
- **The score is ours, not OpenAI's.** Rubric-item grading on a filtered subset, compared
  against a plain-text answer where 83 tasks expected a formatted document. The description must
  say so; the valid claim is fusion versus solo on a launch-table benchmark, never parity with a
  published GDPval number.
- **Coverage is deliberately partial.** 102 of 220. The 23 tasks blocked only by spreadsheet
  references, and the 88 needing artifact production, are later phases.

## 7. Test plan

`test_gdpval_prepare.py` — id-list drift fails the build; re-run over one revision is
byte-identical; a sub-threshold reference fails loudly; the 7 exclusions are asserted by id.
`test_gdpval_definition.py` — revision changes when any hashed input changes; `case_count == 102`;
the judge model resolves in the declared model world.
`test_gdpval_grading.py` — per-item judging; retry then fail on malformed replies; the filter
removes exactly the expected criteria and does so before scoring.
`test_gdpval_aggregate.py` — point-sum scoring with negatives; `required` ignored; all-judges-fail
yields `score = None`, never `0.0`; `coverage` is the exact graded fraction.
`test_gdpval_check_surface.py` — the paid-check disclosure is declared and surfaced.

## 8. Out of scope

Artifact production and artifact-aware grading (the 88 bucket-B tasks). Spreadsheet reference
parsing (the 23 bucket-A tasks). Pairwise-vs-human grading. Submission to OpenAI's grading
service. A second GDPval board — the exam template supports one later without rework.
