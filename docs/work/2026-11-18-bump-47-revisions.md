---
ticket: OME-1958
stack: screamingface-engine
status: in_progress
started: 2026-11-18
finished:
---

# bump-47-revisions — move the 47 revisions OME-1907's grading change touches

## Intent

OME-1907 (#1783, merged) changed how 47 Benchmarks read a wrapped answer letter such as
`ANSWER: $B`, and held their published revisions. Under the owner's 2026-11-17 rule a grading
change moves the revision, and the OME-1909 re-grade (#1896) moves the old entries onto the new
id from their pinned caches. The bump was built in #1896 and moved here on 2026-11-18 (owner),
so the re-grade ships first without moving any leaderboard, and this PR merges and deploys right
before the batch re-grade: old entries are off the Latest board for minutes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: 47 rows get the new
  `published_revision` (their fingerprint) and `regradable_from` (old id, Case Digest).
- `tests/unit/inspect/test_published_revisions.py`: 47 literals, each comment naming its old id.
- `tests/unit/inspect/test_benchmark_fingerprints.py`: the OME-1907 comment says the ids moved.
- Engine `CHANGELOG.md`: one line listing the 47 and why.
- `packages/screamingface/scripts/regrade_batch.py` + `tests/unit/test_regrade_batch_script.py`: the batch re-grade, dry run by default, a JSONL log a re-run resumes from (owner, 2026-11-19).

## Test plan

- `test_published_revisions.py` pins every new id; `test_benchmark_fingerprints.py` shows each
  equals its fingerprint; assembly (`_check_regradable_from`) refuses a stale Case Digest.

## Acceptance

- All 47 rows publish their fingerprint and list their old id with today's Case Digest.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1958.json`, this ledger and the mirror.
- **Commits:** the bump (cherry-picked from 2347b5810 with its references moved from OME-1909 to OME-1958), and this docs commit. Stacked on #1896 (`OME-1909-regrade-from-pinned-cache`), because `regradable_from` lands there.
- **Batch script (2026-11-19):** finds every row each public board shows at an older revision (public Scoreboard reads only), resolves each pinned cache to its score id, and calls `Client.regrade` per entry; `no_pinned_cache` rows are logged for the owner. A 404 on the revisions route stops the run instead of reading as zero entries. Dry run against the dev Scoreboard: 11 old-revision rows (draco-3pass), none with a pinned cache. 5 passed in `test_regrade_batch_script.py`; ruff and pyright clean.
- **Gates:** Engine with the inspect extra: 246 passed in `test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py`, `test_regradable_from.py`, `test_benchmark_bump_regradable.py`, `test_benchmark_foundation.py`.
- **Deviations:** the manifest pins every prior-test edit on this branch against main, #1896's ten included, because the checker accepts only a manifest naming the current branch; re-pin to this PR's two files once #1896 merges.
- **Review (Sergey, 2026-11-19) and live-judge removal (2026-11-20):** cyse4_threat_intelligence, mmmu_multiple_choice and mathvista keep an old id that spans OME-1853's Case change, so their entries from before it (4 cyse4 from 2026-11-06, 1 mmmu from 2026-11-12, as read by the reviewer) miss their pinned cache and need a fresh run; the three row comments and the fingerprint test's HELD note say so. PR body says `Refs`, and this ledger and the mirror stay open until the batch runs. The script's `--live-judge-file` is gone with #1896's live judging (OME-1979). Gates: 36 passed in `test_regrade_batch_script.py` and `test_regrade.py`; ruff and pyright clean.
- **Scheduled run (2026-11-20):** the script can run on a timer: `--when-revision inspect-mmlu_pro=4efebd6cc74c2dca` does nothing until the board serves the new revision (checked against the dev Scoreboard, which answered `waiting: inspect-mmlu_pro serves 145edec84bfc2324`), settled entries are skipped, and `already_current` (an Engine pod not yet updated) is retried instead of settled. The re-grade runs under the operator's own signed-in identity, because the board accepts only a verified email on its list; an in-cluster job would need a service identity, an infra trust change. 6 passed in `test_regrade_batch_script.py`.
- **Owner verify:** merge only after #1896 is deployed, and right before the batch: post to the team (47 boards move), merge, wait for the Engine and the Scoreboard pins to reach prod, check https://leaderboard.screamingface.ai/v1/leaderboard/inspect-mmlu_pro shows `4efebd6cc74c2dca`, then from `packages/screamingface`: `uv run --isolated python scripts/regrade_batch.py` (dry run); re-grade the cyse4 board first with `--apply --benchmark inspect-cyse4_threat_intelligence` and expect `regrade_incomplete` on its entries from before OME-1853; then `--apply` for all, recounting the entries at run time.

## Review follow-up (2026-11-20)

User authorized fixing #1926's outstanding review. Preserve the existing main merge and
approval refresh. Bound discovery to a checked-in table of the 47 board/source/target
transitions, reject unknown selectors and incomplete reads. Hold an advisory process lock
on the log from recovery/read through regrading and fsynced append. Keep permanent refusals
and uncached entries unresolved across runs until an explicit owner resolution is logged.
Recover only an unterminated final record; reject corrupted complete records.

Test plan: mocked board discovery excludes unrelated revisions and boards; missing targets,
wrong revisions, malformed selectors and >200 rows fail closed. Real subprocess contention
must allow only one replay. Crash-tail recovery and durable outcomes are tested, and unresolved
outcomes remain nonzero across reruns. Existing discovery fixtures must now select their one
board explicitly; the prior outcome assertions now include retained unresolved status,
as required by the review. Run SDK and repo gates and the six Engine revision suites.

Implementation: `regrade_transitions.json` pins all 47 exact transitions; an AST contract test
compares it to the Engine rows. `regrade_batch_log.py` holds the process lock, crash recovery,
fsync and explicit owner resolutions. The batch validates targets/selectors, rejects pages
above 200 or shorter than their revision count, and retains unresolved status even when a
row disappears from discovery or a deployment guard is waiting after a rollback.

Review judgment: no SDK API, database, grader or cache-key changes. The file lock deliberately
supports one operator machine and one shared log path, as documented; it is not distributed.
Legacy logs without environment/target identity fail closed and need inspection/archive.
The existing main merges are retained (no history rewrite); the final diff excludes #1896's
already-merged changes and the approval manifest covers only the two revision-test files.

Validation so far: 75 focused batch/SDK tests and 252 Engine revision/fingerprint tests pass.
Full SDK gates (including coverage/build/distribution) and repo gates pass. The initial full
Engine type check saw 16 errors in unchanged optional-inspect tests with the extra installed;
`uv sync --frozen` restores the CI default environment (CI installs inspect after typechecking).
The full Engine gate is rerun in that environment. No live regrade or production write was run.
Read-only production smoke: `--benchmark inspect-mmlu_pro --scoreboard-url
https://leaderboard.screamingface.ai` exited 2 with the expected target-not-deployed message
for `4efebd6cc74c2dca`. No apply flag, login or regrade was used.

Environment diagnosis: the shared Engine venv reacquired optional Inspect packages during
validation. In that mixed environment the full run had 183 failures: chart tests used system
Helm 4.0.0, and six catalogue/import/EnigmaEval assertions reproduced on unchanged main
(`855ec8dd2`, 6 failed / 234 passed in the comparison). A clean temporary default environment
passes all 40 catalogue/import tests; CI-pinned Helm 4.3.2 passes the sampled chart tests.
Full default gates now use `UV_PROJECT_ENVIRONMENT=/private/tmp/pr1926-engine-ci-env` and
`PATH=/private/tmp/pr1926-tools/darwin-arm64:$PATH`. Neither system tools nor unrelated code
were changed. The pre-existing EnigmaEval Draft Feedback assertion remains an optional-Inspect
lane limitation; it is not weakened here.

Final review tightened complete-record validation: required identity fields must be nonempty
strings, successful regrades must name their result, and owner resolutions must contain a
text note. Three regression cases failed before the fix and pass after it (78 focused tests
now). Full Engine default gates pass with the isolated CI environment and Helm 4.3.2.
Final SDK, Engine-default and repo gates are green; fast commit hooks pass. The full SDK gate
was rerun after strict log validation. Commit: `fix(screamingface): bound and harden the revision regrade batch`.
Code review fixes are complete; OME-1958 remains open for dev acceptance and the production batch.
