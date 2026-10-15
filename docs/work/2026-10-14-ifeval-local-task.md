---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-14
---

# ifeval-local-task — serve ifeval as a local inspect Task, delete its folder

## Intent

OME-1527 Work order #15 (PR 15 of 20). IFEval lived in a fifteen-file hand-built folder
(`benchmarks/ifeval/`, eight modules plus the vendored checker) that only the hand-built serving
spine could serve. With the whole-run metric (R1, #1325, and its dict form, #1356), the nltk corpus
at image build (R8, #1388), the scorer's own Draft Feedback words (R9, #1393) and Draft Feedback
without an answer key (R10, #1399) in the plugin lane, and Case ids renumbered to 1..541 accepted
(owner decision 2), it moves to one local Task package under
`screamingface_engine_inspect/local_tasks/ifeval/`, fed to the same importer as inspect_evals,
keeping its id. What must stay the hand-built Benchmark's: prompt bytes, grading rule, score, the
Draft Feedback bytes; and the recorded Corrective Loop golden must replay unchanged (decision 5).
Upstream inspect_evals `ifeval` stays out (its metric is not the published headline, its integer
kwargs keys break through JSON, key 2785 goes out unpatched, keys 1122/1129 grade on a random
letter).

## Planned changes

- `local_tasks/ifeval/{ifeval.py,README.md,__init__.py}` (new): the loader (`google/IFEval` at the
  pinned revision, verified against the vendored official file, key 2785 patched, ids 1..541), the
  `instruction_following` scorer (one dict Score with the paper's four numbers, headline first; the
  per-instruction verdicts and the hand-built Draft Feedback in `Score.metadata`), the
  `ifeval_accuracy` whole-run metric (instruction-level accuracy pooled), the `ifeval` task.
- `local_tasks/ifeval/{grading.py,vendor/}`: moved from the folder (vendor byte-identical; its own
  `__init__` header and `grading.py`'s import path and comments updated).
- `benchmarks.py` / `prepare.py`: the two importer rows; `single_shot.py`: a whole-run metric's key
  that names a Named Score fills that column (`_metric_columns`).
- Delete the rest of `benchmarks/ifeval/` and its tests; `builtins.py` drops the registration;
  `ifeval_checker_failed` loses its last emitter but stays declared on both sides.
- SDK: drop ifeval from `screamingface prepare`; notebooks 07 and 09 and the README say ifeval needs
  an inspect-capable Engine. e2e workflow prepares the `ifeval` bundle with the Engine's preparer.
- Review fixes from #1399 (this PR makes the old name false): rename
  `test_no_imported_row_asks_for_draft_feedback`; loosen the assembly test's exact-list pin.

## Test plan

- `tests/unit/inspect/test_local_task_ifeval.py` (new): conservation literals (four canned Cases
  checked as the hand-built grader checked them; run headline and metrics equal), the Draft
  Feedback record byte for byte, pooled instruction-level accuracy, an abstained Case, the prompt
  bytes of all 541 Cases, the 2785 patch and refusal, the row.
- The surviving grading tests, moved: `test_local_task_ifeval_{grading,grading_feedback,parity}.py`
  (parity now checks the local Task's run metric against the official formulas).
- The ifeval e2e replay against its golden.

## Acceptance

- Prompt bytes, instruction ids and arguments of all 541 Cases equal the hand-built bundle's.
- The Draft Feedback record equals the hand-built route's byte for byte.
- The ifeval golden replays unchanged: 0.9184, 49 of 50 Cases scored, one `model_token_cap`.
- No `benchmarks/ifeval/` folder; nothing emits `ifeval_checker_failed`, and it stays declared.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the shared tests that used the hand-built IFEval: the Corrective
  Loop and combine-on-IFEval tests move to the inspect lane against the local Task
  (`test_corrective_loop_e2e.py`, `test_combine_corrective_rounds.py` renamed into
  `tests/unit/inspect/`; `test_combine_candidates_on_ifeval.py` new, holding the three IFEval tests
  of `test_combine_reducer_candidates.py` and SM-10 of `test_samples_seed_contract.py`); the
  early-grading and conformance tests that used IFEval as their hand-built subject move to
  MedXpertQA (`test_early_grade_connector_cache`, `test_early_grader_crashes`,
  `test_provisional_scores`, `test_benchmark_outcome_conformance`, `test_benchmark_protocol`,
  `test_benchmark_deployment`, `test_inspect_deployment_discovery`, `test_abstain_records`) or drop
  their IFEval branch (`test_benchmark_stage_parity`, `test_builtin_early_score_timing`, which now
  also holds the `_call` helper the deleted incremental proof held, `test_early_grade_safety`,
  `test_finalized_missing_progress`, the early-grade compatibility fixture); `test_abstain_corrective`
  keeps its benchmark-free parts and its check-surface part moves into the new test; the inspect
  conformance tables gain the row (`test_inspect_imported_benchmarks`,
  `test_inspect_task_replay_benchmarks`, `test_imported_catalogue_activity`,
  `replayed_cases_helpers.STAND_IN_METADATA`, `test_benchmark_declaration`, `test_whole_run_metric`,
  `test_published_revisions`); `local_ifeval_helpers.py` (new) prepares a few Cases the way Case
  Preparation does; `local.py`, `pyproject.toml` (vendor fences), `adding-a-benchmark-manually.md`,
  `_bundle_provenance_checks.py` docstrings; `.claude/test-change-approvals/OME-1527.json`
  (rewritten for this branch, 29 files).
- **Import:** `importer screamingface_engine_inspect.local_tasks.ifeval.ifeval:ifeval --key ifeval
  --no-answer-key --keep-sample-metadata --whole-run-metric honour --whole-run-headline
  prompt_level_strict_accuracy --nltk-resource punkt --nltk-resource punkt_tab`
  (HF_HUB_DISABLE_XET=1, `benchmarks` extra): 541 Cases, Case Digest `366210a0…`, Case Source
  `google/IFEval` @ `966cd895` (the hand-built pin), licence Apache-2.0, nltk digest `2da47104…`.
  By hand: `named_scores` (the importer does not read a dict Score), `scorer_reads_answer_key=False`,
  `with_check_surface=True`, `scorer_draft_feedback=True`, `origin="screamingface"`, the TODO prose
  and provenance from the hand-built definition, and the reviewed whole-run metric (TODO prefix
  removed: every key is a share in 0..1).
- **Prompt bytes:** the hand-built bundle (prepared at `1bc092ff6` before the deletion) and the new
  bundle compared Case by Case: 0 of 541 inputs differ, 0 of 541 instruction lists or argument sets
  differ. Pinned by a sha256 literal over the 541 inputs.
- **Draft Feedback bytes:** the hand-built check-surface route and the local Task's, driven through
  the real routes over the real bundles with 11,505 drafts (the 176 recorded replies of the ifeval
  golden against its first 50 Cases, plus five drafts against all 541 Cases; 1,121 passing, 1,711
  partly satisfied): 0 records and 0 `feedback`-intent replies differ. Four of them pinned as
  literals.
- **Conservation literals:** from the hand-built check route and `grade.aggregate` at `1bc092ff6`
  on four canned Cases (official keys 1001, 1000, 1122, 142): Case scores 1, 0, 1, 0; headline 0.5;
  `inst_level_strict_accuracy` 0.4444 (4 of 9 pooled; the Case mean would say 0.5833),
  `prompt_level_loose_accuracy` 0.5, `inst_level_loose_accuracy` 0.5556, `pass_rate` 0.4444.
- **Golden replay:** the Corrective Loop golden (2 members, a judge, 3 rounds, limit 50) replays on
  the zero-key replay stack from its 177-row snapshot, every Candidate, judge and coaching call
  answered from the cache (a miss fails loudly there): 0.9184, 49 of 50 scored, Case 10 (official
  1069) failed `candidate:model_token_cap`, as recorded. Changed in the golden: `expression_sha`
  (`eef358f5…` → `6411a99f…`, re-rendered by the replay once the published revision returned, deviation (5); it read
  `77cb3bc9…` while the revision had moved) and the Case-id keys of `case_statuses` /
  `case_failures`, remapped by one rule: official key → its 1-based position in the pinned split
  (which is also its row in the official file), re-sorted as the bless tool sorts them. Every
  status, failure and the score are unchanged.
- **Revision:** published `1cba769ece27f7ef`, unchanged (hand-set, deviation (5)); the local Task's
  fingerprint is `ada07458a23c55ab` (it was `9d88d67cf2ce2be5` before the abstain contract,
  deviation (6), edited the Task's source).
- **Report:** as decided for the other moves, thinner. Kept: the headline, the four hand-built run
  metrics under their keys (the card's `pass_rate` included). New: four Named Scores (instruction
  levels pooled), the tally's `correct` and `scored_cases`. Lost: one Check per instruction
  (labelled MET/UNMET) becomes one Check per Case whose evidence lists each instruction's id,
  description, strict and loose verdict; each Case grade's `follow_all_strict`, `follow_all_loose`,
  `strict_checks_passed`, `loose_checks_passed` metrics; grade method `deterministic` becomes
  `inspect_scorer`; a Candidate failure's upstream spelling moves from `metadata.source_code` to
  `metadata.source_error.source_code` and `row_index` / `error_kind` are gone (the plugin lane's
  shape for every Benchmark); a checker crash fails the Case as `scorer_error`.
- **Commits:** see the PR.
- **Gates:** relevant files only: with the inspect extra, 908 passed in the touched inspect-lane
  files and 203 in the touched lane-1 files; extra-less, 167 passed and 17 skipped (the inspect
  files); SDK `test_runtime_cli.py`, `test_engine_url4_contract_fixtures.py`,
  `test_example_notebooks.py` 81 passed, `check_notebooks.py` clean; the ifeval e2e board replay
  passed. ruff + format clean, pyright 0 errors on the 43 touched engine files extra-less and with
  the extra. Append-only check run by hand (OME-1575): fails only on the 12 deleted `test_ifeval_*`
  files and the 5 renamed ones (`test_ifeval_{grading,grading_feedback,golden_parity}` →
  `inspect/test_local_task_ifeval_*`, `test_corrective_loop_e2e`, `test_combine_corrective_rounds`
  → `inspect/`), which the manifest cannot approve; every edited test passes through
  `OME-1527.json`. Mutation checks: joining the Draft Feedback words with "; " turns the byte test
  red; dropping the pooled-column override turns the run-numbers test red. Size: over the ~500-line
  cap from the deletions and the moved tests (+1,777 / −8,311 with renames detected).
- **Deviations:** (1) A shared-lane change: a whole-run metric's dict key that names a Named Score
  now fills that column (`single_shot._metric_columns`), so the instruction-level Named Scores
  publish the pooled number, not the mean of Case fractions; no other row has both a whole-run
  metric and Named Scores, so nothing else moves. (2) The early-grading and corrective tests needed a
  new subject (above); the corrective ones now run only in the inspect lane, so lane 1's coverage
  gate loses them. (3) `BenchmarkAggregation.missing_case_result` lost its last user (the hand-built
  IFEval) and is left in place: the parallel healthbench move edits the same file; owner call
  whether to remove it here or there, as draco's fix (8) did for its hooks. (4) The Benchmark now
  publishes `dataset_url` (`https://huggingface.co/datasets/google/IFEval`), reversing a deliberate
  choice: the hand-built definition left it out because "the IFEval dataset is vendored inside this
  Engine, so no single public URL is authoritative" (added with the catalogue seeding in
  `9077aceec`, pinned by `test_the_ifeval_benchmark_publishes_no_dataset_link`, deleted here with
  the hand-built tests). That reason no longer holds: the Cases are now loaded from the Hub at the
  pinned revision (the Case Source the importer records and the Case Digest seals), and the
  vendored official file is only the authority they are checked against (key 2785 patched, any
  other difference refused). The link names where the Cases come from, like every other imported
  row's. (5) ifeval publishes its hand-built revision `1cba769ece27f7ef` (owner decision OME-1610: a
  Benchmark's published version must not move as a side effect of a code move; merging draco moved
  draco-3pass's and hid its leaderboard results). `BenchmarkSpec.published_revision` is hand-set
  and not hashed: the Engine publishes it as is (routes, `Benchmark.revision`) and NEVER the
  computed fingerprint, with no runtime comparison and no assembly refusal, so a mismatch can never
  take a Benchmark down on prod. The fingerprint is exposed as `ImportedBenchmark.computed_revision`,
  and the alarm is a test: `test_published_revisions.py`'s `_FINGERPRINTS` records the fingerprint
  each hand-set revision stands for (`ifeval`: `ada07458a23c55ab`), and
  `test_a_pinned_benchmark_still_computes_the_fingerprint_its_published_revision_stands_for` fails
  in CI, naming both values, when it moves. The proof the exam is unchanged is the free Corrective
  Loop golden replaying with zero misses on the final code (revision `1cba769ece27f7ef`, 0.9184, 49
  of 50, every status and failure as recorded; golden unchanged by the redesign). This replaces an
  earlier round's `kept_revision=(published, stands_for)`, cherry-picked from #1403's `5f3df2ed2`,
  which refused assembly on a mismatch; the owner redesigned it so prod never refuses. #1403 makes
  the identical change for healthbench (`5263997b2`), and this branch mirrors it byte for byte to
  avoid add/add conflicts: the `single_shot.py` hunks, the `BenchmarkSpec` field and its
  `_assemble` line, `test_published_revision.py` but its expected rows, and the `_FINGERPRINTS`
  block of `test_published_revisions.py` but its rows. (So the field's comment says "every row but
  the migrated healthbench pair", true once both merge, not on this branch alone.) `test_only_rows_with_an_equivalence_proof_set_a_published_revision`
  expects `{"ifeval": …}` here and #1403 its healthbench pair, as do the two `_FINGERPRINTS` dicts;
  whichever of the two merges second resolves both to the union of the three rows. (6) The abstain contract for the whole-run metric (#1403 hands it an abstained
  Case's Score zeroed and marked `candidate_abstained`, the lane's `CANDIDATE_ABSTAINED`, sometimes
  as a bare 0.0 with no metadata but the mark): `ifeval_accuracy` counts a marked Score as a prompt
  failed strictly and loosely whatever verdicts it carries; its listed instructions count as
  failed, and a bare Score counts as one failed prompt with ZERO instructions (the count is
  unknown; a guess would be a wrong number, so the instruction-level denominator omits that Case's
  instructions). An unmarked Score without instructions is still refused (KeyError). Done here so
  the two PRs merge in either order; until #1403 merges nothing sends the mark, so no number moves.
- **Owner-verify:** (1) the next Engine image build prepares the `ifeval` bundle, its Case Digest
  and nltk digest match; (2) one paid IFEval Corrective Loop run after merge on an Engine with the
  inspect extra, its score read beside the golden's 0.9184 (the replay already proves the recorded
  bytes and score; this run checks the live path); (3) notebooks 07 and 09 opened against
  `just local-stack-notebooks` once; (4) the `missing_case_result` hook, deviation (3).
- **Review fixes (#1407):** (a) nothing proved ifeval's checker reads the bundled punkt corpus
  (#1388 deferred that proof to this PR; 64 of the 541 Cases tokenize): new
  `test_ifeval_grades_with_the_bundled_tokenizers_and_no_network` runs Case Preparation's real
  nltk step (downloads punkt and punkt_tab into the bundle and checks they seal to the row's
  digest; needs the network, as the image build does, and never skips), then, with sockets and
  nltk's downloader refused, nltk's path emptied and its loaded tokenizers forgotten, shows
  counting sentences raises LookupError before install and three Cases (official keys 3739 twice,
  2849) grade 1, 1, 0 after; `test_nltk_data_at_image_build.py`'s two "#15 does" placeholders
  now name it. Mutation: the installer not pointing nltk at the bundle turns it red. (b) the
  refusal of changed instruction ids or arguments was untested: new
  `test_changed_instructions_are_refused_never_patched` (ids, kwargs; keys 1000 and 2785).
  Mutation: replacing the check with `False` turns both red. (c) the root README's Quickstart
  evaluates `ifeval`, which the plain Engine no longer lists: a note in the SDK README's words.
  (d) deviation (4) above. Gates: with the inspect extra, `test_local_task_ifeval.py`,
  `test_local_task_ifeval_grading.py`, `test_local_task_ifeval_parity.py`,
  `test_nltk_data_at_image_build.py` 44 passed; extra-less, the two touched test files skip at
  the `inspect_ai` import only; ruff, format and pyright (extra-less) clean on the three touched
  test files; `OME-1527.json` approves the docstring-only edit of the image-build test.
  Second round (OME-1610): deviations (5) and (6). New tests
  `test_an_abstained_score_fails_its_prompt_and_every_listed_instruction` and
  `test_a_bare_abstained_score_is_one_failed_prompt_with_no_instructions`; mutations (abstained
  prompt not forced to fail, mark ignored, bare Score read for its instructions) each turn one or
  both red. With the inspect extra, `test_published_revisions.py`,
  `test_local_task_ifeval{,_grading,_parity}.py`, `test_task_replay_rows.py`,
  `test_inspect_task_replay_benchmarks.py` 253 passed, and the Corrective Loop / combine tests that
  read the check route 14 passed; the free ifeval golden replay passed; ruff, format and pyright
  (extra-less) clean on the touched files; `OME-1527.json` re-approves `test_published_revisions.py`
  and the golden. Third round (OME-1610 redesign): `kept_revision` replaced by the hand-set
  `published_revision` (deviation (5)); `test_kept_revision.py` becomes `test_published_revision.py`.
  With the inspect extra, `test_published_revision.py`, `test_published_revisions.py`,
  `test_local_task_ifeval.py`, `test_task_replay_rows.py`, `test_inspect_task_replay_benchmarks.py`
  236 passed; a wrong recorded fingerprint fails with the bump message; the free ifeval golden
  replay passed with the golden untouched; ruff, format and pyright (extra-less) clean.
