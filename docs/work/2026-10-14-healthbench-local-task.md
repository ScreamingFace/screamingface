---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-14
---

# healthbench-local-task — serve healthbench worst-30 and professional as local inspect Tasks, delete their folder

## Intent

OME-1527 Work order #20 (PR 20 of 20, the last move). HealthBench lived in a fourteen-file
hand-built folder (`benchmarks/healthbench/`) serving two Benchmarks over one prepared answer key:
`healthbench-worst30` (the frozen hardest 157 conversations, scored by the plain mean, negatives
kept) and `healthbench-professional` (all 525, scored by the official clipped mean). With the
judge redraw (R3), concurrent grading of judged Cases (R4), the whole-run metric (R1, row 2),
conversation-shaped Cases (R14, row 19, #1394) and the run's verdict counts (row 18b, #1401) in
the plugin lane, and the thinner Report accepted (owner decision 1), both move to one local Task
package under `screamingface_engine_inspect/local_tasks/healthbench/`, fed to the same importer as
inspect_evals, keeping their ids. What must stay the hand-built Benchmark's: prompt bytes (the
115 conversation Cases included), judge bytes, grading rule, score; and the recorded worst-30
golden must replay unchanged (decision 5). Acceptance 3 of OME-1527 lands here: the manual guide
says the hand-built lane is for MedXpertQA.

## Planned changes

- `local_tasks/healthbench/{healthbench.py,README.md,__init__.py}` (new): the loader
  (`datasets.load_dataset` at the pinned revision, all 525 rows in file order; worst-30 keeps the
  frozen selection in its frozen order), the chat as inspect messages, the points rubric in Sample
  metadata, the `healthbench_rubric` scorer (one judge call per rubric line through
  `judge_until_parsed`, the reference grader prompt, earned over winnable, unclamped, verdict
  counts in `Score.metadata`), the `healthbench_clipped_mean` whole-run metric, and the
  `healthbench_worst30` / `healthbench_professional` tasks.
- `local_tasks/healthbench/{prompts,scoring,subset}.py`: moved from the folder; `scoring.py` loses
  `unclipped_mean` (worst-30's mean is the lane's own tally), `subset.py` keeps only the frozen HF
  ids (`WORST30_CASE_IDS` and `subset_sha()` go: the revision no longer reads them).
- `benchmarks.py` / `prepare.py`: the four importer-generated rows; the judge pinned on the row
  (`JudgeSpec`, the hand-built `JUDGE_PARAMS`), `candidate_input_envelope=True`, the clipped mean
  honoured on professional only, provenance carried over, `origin="screamingface"`.
- Delete the rest of `benchmarks/healthbench/` (11 files) and its 7 test files (the grading one
  moves with `prompts.py`/`scoring.py`); `builtins.py` drops both registrations.
- Remove what the move orphans: `benchmarks/rubric_draft_feedback.py`,
  `shared_grading/rubric.py`, `shared_grading/mean_scorer.py`, and in
  `shared_grading/judge_evidence.py` the url4 rubric-verdict wiring (`rubric_verdict_call`,
  `rubric_evidence_record_key`, `require_positive_int`) and `extract_json_array`, with their tests.
- SDK: drop healthbench from the hand-built prepare list; e2e bundle maps; paid shared-bundle map;
  notebook 08 says it needs an inspect-capable Engine; the e2e workflow prepares the
  `healthbench-worst30` bundle.
- Keep the e2e golden (decision 5): it replays its recorded calls unchanged; `revision` and
  `expression_sha` regenerate from the free replay.

## Test plan

- `tests/unit/inspect/test_local_task_healthbench.py` (new): conservation literals (five canned
  Cases, two of them conversations, graded as the hand-built grader graded them; headlines
  worst-30 −0.1875, professional 0.0), the verdict counts, the clip over the run mean, the judge's
  wire (route, params, one user message, the hand-built prompt sha for a conversation Case, and one
  call through the real connector both ways), the Candidate prompt bytes for both chat shapes, the
  loader's refusals, the rows, an abstained Case.
- `tests/unit/inspect/test_local_task_healthbench_scoring.py` (moved): the grader template sha, the
  reference prompt assembly, `case_score`, `clipped_mean`.
- The healthbench-worst30 e2e replay against its golden.

## Acceptance

- Prompt bytes and rubrics of all 682 Cases of both Benchmarks equal the hand-built bundle's;
  every judge request equals the hand-built one byte for byte.
- The healthbench-worst30 golden replays unchanged: −0.091, 124 Cases scored, 33 failed
  `upstream_error`.
- No `benchmarks/healthbench/` folder; the manual guide names MedXpertQA as the lane's Benchmark.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (80 files, +2,013 / −6,521 before this ledger), plus: the shared
  tests that named the folder (stage parity, early-score timing, early-grade compatibility and its
  fixture, activity helper, asset isolation, deployment, outcome conformance, protocol, provenance,
  finalized-missing progress, native case index, fresh judge retry, grading-error integrity,
  abstain families and records, conversation cases, the declaration and family tables, the
  whole-run opt-in list, the revision literals); the tests of the orphaned shared modules (shared
  aggregation, case grader, concurrent grading, inverted grade, judge evidence, token exhaustion);
  pointer comments in `conversation_input.py`, `benchmark_aggregation.py`, `Dockerfile.benchmark`,
  `adding-an-imported-benchmark.md`, two judge-pin test comments;
  `.claude/test-change-approvals/OME-1527.json` (rewritten for this branch, 36 files).
- **Import:** `importer …healthbench.healthbench:healthbench_worst30 --key healthbench-worst30` and
  `…:healthbench_professional --key healthbench-professional --whole-run-metric honour`, both
  `--no-answer-key --keep-sample-metadata` (HF_HUB_DISABLE_XET=1, `benchmarks` extra): 157 Cases,
  Case Digest `086738fb…`, and 525 Cases, Case Digest `9d6822d9…`; Case Source
  `openai/healthbench-professional` @ `349962fd` (the hand-built pin), licence MIT. The importer did
  not detect the judge (its model is the scorer's default), so the `judge_model` kwarg and the
  `JudgeSpec` were added by hand, as for draco; every TODO resolved from the hand-built definition
  (titles, descriptions, focus, difficulty `hard`, paper/authors/citation/harness, licence and
  note, content warning, baselines, frontier score, notebook `08_healthbench`).
- **Prompt bytes:** the hand-built bundle (prepared from `1bc092ff6` before the deletion) and the
  new bundles compared Case by Case, as served to the Candidate (`candidate_input_envelope`):
  professional 0 of 525 inputs differ (115 conversations), worst-30 0 of 157 (43 conversations);
  0 rubrics differ (every line's id, text and points, and the HF row id).
- **Judge bytes:** every grader prompt the hand-built route rendered (all 525 Cases, 1,135 rubric
  lines, a fixed answer per Case) equals the local Task's, sent to the same route with the same
  params in the same order and an empty intent (worst-30: 332 lines, also 0 differ). A probe sent
  all 1,135 through the real connector into a mock gateway both ways (the hand-built judge
  RelExpr, and inspect's one user message through the judge provider): 0 request bodies differ.
  The committed test repeats that probe for one prompt.
- **Golden replay:** healthbench-worst30 replays its 764 recorded calls (124 answers each from the
  three members and the synthesizer, 268 judge calls) on the zero-key replay stack and matches the
  golden: −0.091, 124 Cases scored, the same 33 `upstream_error` Candidate failures. The golden
  changed in `revision`, `expression_sha`, and its Case keys: worst-30 Case ids were positions in
  the 525-row file and are now 1..157 in the frozen order (owner-accepted renumbering; old 20 is
  new 1), so every status and failure is the same entry under its new number.
- **Conservation literals:** from the hand-built expression at `1bc092ff6`, driven end to end on
  the canned replies (routes, `;retry=2`, aggregate, both means): Case scores 0.25, 0.5, −2.5, 1.0
  and one failed Case (`judge_reply_invalid`); headlines worst-30 −0.1875, professional 0.0.
- **Revision:** healthbench-worst30 `39cfd96b068f7230` → `f12c3e30661ea9d3`,
  healthbench-professional `d8fb037307f35415` → `44ddda05be338699`; owner-accepted (no external
  users). The scoreboard fixture (`engine_catalog.json`, a recorded engine response that still holds
  draco's pre-move revision too) and the SDK's synthetic tape and bless documents keep the old
  string: they are recorded or made-up data, not checks of the live revision.
- **Report:** thinner, as decided: one Check per Case carrying each line's points, verdict and the
  judge's words, the redraw count and the verdict counts; no Check per rubric line; judge cost per
  Case. Kept: `scored_cases`. New: `correct`, `verdicts_expected` / `accepted` / `rejected`. Lost
  (the hand-built mean scorer published them, the SDK reads only `pass_rate`): `pass_rate` (the
  Report's "pass rate" cell now shows "—"), `score_sd`, `verdict_coverage`,
  `judge_invalid_replies`. The grading warning works: a graded Case reports expected = accepted
  (a line with no verdict fails its Case, as hand-built), so `verdicts_rejected` is 0 and the
  warning rightly stays silent; pinned.
- **Failure codes:** `judge_reply_invalid` is still emitted (a line never parsed). A judge CALL
  that fails outright (429 past its retries, a token cap) now fails the Case as `scorer_error`
  with the cause in the Check evidence, as for draco. `incomplete_verdicts` and
  `no_positive_points` lost their emitter (`shared_grading/rubric.py`, deleted) and
  `healthbench_grading_failed` its (`healthbench/grade.py`); all stay declared on both sides.
- **Orphans:** removed (production code whose last user was this folder, with their tests):
  `benchmarks/rubric_draft_feedback.py` (healthbench's check policy was its last adapter; the offer
  was already off), `shared_grading/rubric.py`, `shared_grading/mean_scorer.py` (four shared
  aggregation test files used it as their scorer; they now use a stand-in `mean_score`), and in
  `judge_evidence.py` `rubric_verdict_call`, `rubric_evidence_record_key`, `require_positive_int`,
  `extract_json_array`. Left, and named here: `case_records.build_case_record` and
  `grading_endpoints.case_grade_endpoint` (generic record/route builders; only their own tests use
  them now), and `world/fresh_judge_retry.py`'s url4-retry half (the connector still applies it,
  but no hand-built judge route with `;retry=` is left; the redraw helper uses its other half).
- **Commits:** see the PR.
- **Gates:** relevant files only (listed in the PR), with and without the inspect extra; ruff +
  format clean; extra-less pyright 0 errors on the 43 touched engine files and the touched SDK
  files. Full gate = pre-push hook + CI. Append-only check run by hand (the hook passes silently in
  worktrees, bug `OME-1575`): the engine stack fails only on the 7 deleted `test_healthbench_*.py`
  files (one moved to `inspect/test_local_task_healthbench_scoring.py`), which the manifest cannot
  approve; every edited test passes through `OME-1527.json`; the SDK stack passes. Mutation checks:
  clamping each Case before the clip turns the professional headline and clip tests red; joining
  conversation turns with one newline turns the judge-bytes test red; both edited back in place.
  Size: well over the ~500-line cap from the deletions; the owner waived the cap for the earlier
  moves (#1387, #1395).
- **Deviations:** (1) The golden's Case keys are renumbered (see Golden replay): the importer numbers
  Cases 1..N, and decision 5 allows only `revision` and `expression_sha` to regenerate, so the
  owner's renumbering decision and decision 5 meet here; every recorded outcome is unchanged.
  (2) Shared tests that used HealthBench as their hand-built subject moved to MedXpertQA (asset
  isolation, outcome conformance, grading-error rendering, finalized-missing progress, case index,
  the SDK manifest-status test). The tests that need a hand-built JUDGE have no subject left and
  went: the inner fan-out fail-fast pin and three full-protocol judge tests in
  `test_grading_error_integrity.py`, the five rubric-verdict cases in `test_fresh_judge_retry.py`,
  the judge-graded abstain case (re-pinned on the local Task). (3) The manual guide says MedXpertQA
  is the lane's Benchmark and that IFEval still lives there until its own move (row 15) lands;
  OME-1527 acceptance 3 is fully true once that PR merges. (4) The paid case-provenance helper's
  shared-bundle map lost its last entries and went, with its test (no Benchmark shares a bundle).
- **Review fixes (#1403):** (1) The whole-run metric skipped the abstain rule (OME-1289): it read
  the raw inspect Scores the adapter kept, so on professional an abstained Case the judge rated
  1.0 made the headline (0.25 + 1.0) / 2 = 0.625 while its Case Result showed 0.0 (headline
  should be 0.125), and an abstained Case whose judge failed (kept at 0.0, but no Score filed)
  stopped the run with `AggregateError` after every model call was paid. Both reproduced red on
  the pushed head. The tally now hands the metric 0.0 for every abstained Case (the kept Score
  with only its value replaced, or a bare 0.0 Score when none was filed), and its consistency
  check, which compared only Cases with Attempts, now refuses by the metric's name any graded
  Case whose Score is not its Case Result score (compared at the score's 4 places). The fix is
  in the shared tally, so it is lane-wide: contracteval's F1, ARC-AGI-2's per-task accuracy and
  (on #1407) IFEval's metrics read the same 0.0; contracteval's, ARC-AGI-2's and draco's tests
  still pass. Pinned by the abstain test now run on both keys, a new variant where the
  abstained Case's judge fails (0.125 on both keys, no crash), and two tests in
  `test_whole_run_metric.py` (`zero_sample_score` keeps the metadata; a split Case is refused).
  (2) `judge_redraw.py`'s `JudgedItem` docstring named `judge_invalid_replies`, which this PR
  deleted; it now names the `judge_redraws` evidence key. (3) `prompts.py` links simple-evals at
  `blob/main` while both rows cite `652c89d0…`. The header was left as is: `task_source` hashes
  every `.py` file in the package, so editing it moves both revisions and the golden again
  (draco's deviation 9 chose the README for the same reason). The pinned link went into the
  Task README instead, which is not hashed. No revision moved (`test_published_revisions`
  passes), so the golden replay was not re-run.
- **Owner-verify:** (1) the next Engine image build prepares the `healthbench-worst30` and
  `healthbench-professional` bundles and their Case Digests match; (2) one paid healthbench-worst30
  run after merge on an Engine with the inspect extra, its score read beside the golden's −0.091
  (the replay already proves the recorded bytes and score; this run checks the live judge path
  only), and a `limit=1` professional run; (3) notebook 08 opened against
  `just local-stack-notebooks` once; (4) the renumbered golden keys, deviation (1); (5) the lost
  `pass_rate` cell and run metrics (decision 1 covers them; say if the Report should get them back
  through a dict whole-run metric, contracteval's shape).
