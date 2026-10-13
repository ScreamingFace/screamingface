---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# draco-local-task — serve draco and draco-3pass as local inspect Tasks, delete their folder

## Intent

OME-1527 Work order #18 (PR 18 of 20). DRACO lived in a seventeen-file hand-built folder
(`benchmarks/draco/`) serving two Benchmarks, `draco` (five judge passes) and `draco-3pass`
(three), that only the hand-built serving spine could serve. With the judge redraw (R3), concurrent
grading of judged Cases (R4), a pinned judge seed per pass (R12, #1389), the retrieval policy on
the row (R13, #1390) and their review fixes (row 16b, #1392) in the plugin lane, and the thinner
Report accepted (owner decision 1), both move to one local Task package under
`screamingface_engine_inspect/local_tasks/draco/`, fed to the same importer as inspect_evals,
keeping their ids. The three things that must stay the hand-built Benchmark's: prompt bytes,
grading rule, score; and the recorded draco-3pass golden must replay unchanged (decision 5).

## Planned changes

- `local_tasks/draco/{draco.py,README.md,__init__.py}` (new): the loader (`datasets.load_dataset`
  at the pinned revision, all 100 rows in order, the rubric in Sample metadata), the
  `draco_rubric` scorer (one judge call per criterion per pass through `judge_until_parsed`,
  pass `k` stamped `seed=k`, the paper's pass arithmetic), the `draco` and `draco_3pass` tasks.
- `local_tasks/draco/{prompts,scoring}.py`: moved from the folder; `prompts.py` keeps the judge
  bytes and drops the url4 escaping (`judge_intent` → `JUDGE_SYSTEM`, the bytes the gateway saw).
- `benchmarks.py` / `prepare.py`: the four importer-generated rows, the judge pinned on the row
  (`JudgeSpec(seed_per_pass=True)`, `web_search=false`), the retrieval policy, provenance carried
  over, `origin="screamingface"`.
- Delete the rest of `benchmarks/draco/` (15 files) and its 17 test files; `builtins.py` drops
  both registrations. `draco_grading_failed` loses its last emitter but stays declared on both
  sides.
- SDK: drop draco from the hand-built prepare list; the README and notebooks 00, 01, 06 say draco
  needs an inspect-capable Engine.
- Keep the e2e golden (decision 5): the e2e workflow prepares the `draco` and `draco-3pass`
  bundles with the Engine's own preparer, and the golden replays its recorded calls unchanged;
  only `revision` and `expression_sha` are regenerated from the free replay.

## Test plan

- `tests/unit/inspect/test_local_task_draco.py` (new): conservation literals (four canned Cases
  graded as the hand-built grader graded them, headline 0.5 = hand-built), the one deliberate
  difference (a redraw that parses counts), the judge's wire (route, params, seed per pass, the
  system and user message bytes), the Candidate prompt bytes, the rows.
- the draco-3pass e2e replay against its golden; the e2e failure rehearsals (draco-3pass board).

## Acceptance

- Prompt bytes and rubrics of all 100 Cases equal the hand-built bundle's; every judge request
  equals the hand-built one byte for byte.
- The draco-3pass golden replays unchanged: 0.3592, all 100 Cases scored.
- No `benchmarks/draco/` folder; nothing emits `draco_grading_failed`, and it stays declared.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the shared tests that named the folder (stage parity, early
  score timing, early-grade compatibility and its fixture, activity helper, native case index,
  asset isolation, deployment, outcome conformance, protocol, provenance, finalized-missing
  progress, fresh judge retry, grading-error integrity, discovery, the declaration and family
  tables, the revision literal); the orphaned `tests/unit/benchmark_support.py` (its one user was
  the deleted draco fresh-retry case); stale draco examples in `adding-a-benchmark-manually.md`,
  `Dockerfile.benchmark`, `local.py`; the SDK's CLI test, paid shared-bundle map, e2e bundle maps
  and failure rehearsals; `.claude/test-change-approvals/OME-1527.json` (rewritten for this branch).
- **Import:** `importer …draco.draco:draco --key draco` and `…:draco_3pass --key draco-3pass`,
  both `--no-answer-key --keep-sample-metadata --retrieval-policy draco/reproduction` with the
  seven `--retrieval-excluded-domain`s (HF_HUB_DISABLE_XET=1, `benchmarks` extra): 100 Cases each,
  Case Digest `2302f1a5…`, Case Source `perplexity-ai/draco` @ `ce076749` (the hand-built pin),
  licence MIT. The importer did not detect the judge (its model is the scorer's default), so the
  `judge_model` kwarg and the `JudgeSpec` were added by hand; every TODO resolved from the
  hand-built definition (title, description, focus, difficulty `hard`, paper/authors/citation/
  harness, licence and note, baseline NotPublished, frontier 0.705, notebook `06_draco`).
- **Prompt bytes:** the hand-built bundle (prepared at `3a1d9afbb` before the deletion) and the new
  bundle compared Case by Case: 0 of 100 inputs differ, 0 of 100 rubrics differ, and the judge's
  view of every criterion (id, requirement, type) is identical for all 3,934 criteria. A probe
  rendered one judge call both ways through the real connector into a mock gateway: identical
  request bodies (system message = the url4 intent's bytes, user message = the U+2028-joined
  context, params in the same order, then `seed`).
- **Golden replay:** draco-3pass replays its 11,902 recorded calls (100 Candidate answers with
  search, 11,802 judge calls) on the zero-key replay stack and matches the golden: 0.3592, all
  100 Cases scored, no failures. Only `revision` and `expression_sha` changed in the golden.
- **Conservation literals:** from the hand-built verdict parser and scoring at `3a1d9afbb`
  (`build_evidence_record` → `valid_verdicts` → `group_by_judge_pass` → `score_case`, then the
  round-4 mean): Case scores 0.5, 0.6667, 0.3333 and one failed Case; headline 0.5.
- **Revision:** draco `62718f04ea1a980f` → `c6fb6f500dc58622`, draco-3pass `2634cec91fd0f19a` →
  `e8c3ad925dcd4d4a`; owner-accepted (no external users).
- **Report:** thinner, as decided: one Check per Case carrying each criterion's per-pass verdicts
  and the judge's words, the redraw count, pass rate, per-axis scores, Factual Accuracy and the
  verdict counts; no per-criterion Check; judge cost per Case. The run metrics the hand-built
  scorer published beside the headline (`pass_rate`, `axis_scores`, `verdict_coverage`, …) are not
  served; Case metadata no longer carries `domain` (it rides the private Grading Material).
- **Commits:** see the PR.
- **Gates:** relevant files only (listed in the PR), ruff + format clean, extra-less pyright on
  touched files. Full gate = pre-push hook + CI. Append-only check run by hand (the hook passes
  silently in worktrees, bug `OME-1575`): it fails only on the 17 deleted `test_draco_*.py` files,
  which the manifest cannot approve; every edited test passes through `OME-1527.json`. Size: well
  over the ~500-line cap from the deletions (+1,609 / −6,631 lines); the owner waived the cap for #1387.
- **Deviations:** (1) A judge reply with no verdict is redrawn (twice, outside the gateway cache)
  before its criterion is left out of that pass; the hand-built grader asked once. Same outcome
  whenever the redraws also fail (pinned), a verdict where one redraw parses (pinned). (2) A judge
  CALL that fails outright (token cap, 429 past its retries) now fails the Case as `scorer_error`
  with the cause in the Check evidence; the hand-built Benchmark surfaced the connector's own code
  (`model_token_cap`, `rate_limited`) and retryability as the Failure. The two e2e failure
  rehearsals that pinned those codes now pin `scorer_error` plus the cause in the evidence;
  `judge_cutoff` now reports `retryable` as unstated (None) where it was True. The seven tapes
  themselves are unchanged (the fake gateway matches by model). (3) `test_benchmark_asset_isolation`
  lost its "reads assets once" test: that memo was DRACO's runtime, deleted; its other test moved
  to HealthBench. Other shared tests that used DRACO as their hand-built subject moved to
  HealthBench or IFEval. (4) The default `screamingface up` Engine no longer lists draco (no inspect
  extra), and the SDK quickstart (README, notebooks 00 and 01) uses draco; they now point to an
  inspect-capable Engine (`just local-stack-notebooks` serves one). Owner decision pending: keep
  that, or switch the quickstart Benchmark.
- **Review fixes (second commit set):** (5) `scoring.py` moved unchanged but its tests had gone
  with the folder; they are restored as `tests/unit/inspect/test_local_task_draco_scoring.py`
  (14 tests, import repointed). Dropped: the three tests of helpers the move deleted,
  `case_results.group_by_judge_pass` (2 tests; the scorer groups per pass itself, pinned by
  `test_local_task_draco.py`) and `grade._mean_optional_grade_metrics` (1 test; no Candidate-level
  accuracy mean is published on the thinner Report). Mutation check: scoring an absent Factual
  Accuracy axis as 0.0 turns the restored file red and leaves `test_local_task_draco.py` green.
  (6) The Report's "Grading did not fully land" warning (`report_view.py` `_grading_html`) can no
  longer fire for draco: the hand-built `grade.py` summed each Case's `verdicts_rejected` /
  `invalid` / `missing` into the Candidate's metrics, and the scorer now keeps its verdict counts
  in each Case's Check evidence only. Not rebuilt here (decision 1, the thinner Report); a Known
  limitation, owner call. (7) Which pass came back empty changes the score (an empty middle pass
  scores 0, an empty last pass drops out), as it did hand-built; pinned by
  `test_an_empty_middle_pass_scores_zero_but_an_empty_last_pass_drops_out`, owner call whether to
  treat an empty pass as missing wherever it sits. (8) `BenchmarkAggregation`'s error-case,
  missing-material and hook-failure hooks lost their only user (draco's `grade.py`) and are
  removed with their five tests; `healthbench/prepare.py` carries the importlib rationale it
  pointed to in the deleted draco preparer; the 429 rehearsal is renamed (it no longer asserts
  retryability). (9) Source citations go in the Task README, not the `.py` headers: the paper's
  arXiv version was never recorded; `scoring.py`'s reference is linked at `619b9009`. A header
  edit would move both revisions and the golden.
- **Owner-verify:** (1) the next Engine image build prepares the `draco` and `draco-3pass` bundles
  and their Case Digests match; (2) one paid draco-3pass run after merge on an Engine with the
  inspect extra, its score read beside the golden's 0.3592 (the replay already proves the
  recorded bytes and score; this run checks the live search and judge path only); (3) notebooks 00
  and 06 opened against `just local-stack-notebooks` once; (4) the quickstart decision in
  deviation (4); (5) the lost grading warning, fix (6); (6) the empty-pass rule, fix (7).
