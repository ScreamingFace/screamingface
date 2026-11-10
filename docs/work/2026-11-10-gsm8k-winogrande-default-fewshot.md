---
ticket: OME-1860
stack: screamingface-engine
status: done
started: 2026-11-10
finished: 2026-11-10
---

# gsm8k-winogrande-default-fewshot — serve gsm8k and winogrande with inspect_evals' default worked examples

## Intent

gsm8k and winogrande were imported with `fewshot=0`, so every Case was the bare question,
while inspect_evals' default sends 10 (gsm8k) and 5 (winogrande) worked examples first. Neither
paper prompts a model, so inspect's default run is the only reference number that exists. Owner
decision on OME-1860 (2026-11-10): serve inspect's default.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`: drop `task_args` from
  both rows, re-seal `case_digest` / `case_set_digest`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: move both
  `published_revision`s; winogrande's description drops "0-shot".
- Revision and fingerprint pins in `tests/unit/inspect/` (published revisions, fingerprints,
  bump command, inverted grade); a CHANGELOG line.
- Re-audit `inspect-gsm8k` and `inspect-winogrande` with the `sf-benchmark-fidelity` agent and
  replace their records.

## Test plan

- The fingerprint and published-revision pins go red on the row change, then green on the new ids.
- Production `replay_with_provenance` reproduces the pinned digests and Case counts (1,319 / 1,267).
- `fidelity_check.py` reads every record fresh.

## Acceptance

- Every Case of both Benchmarks opens with inspect_evals' default worked examples, byte-equal to
  inspect's system text joined to its user text.
- Both records are fresh against the new fingerprints.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_benchmark_bump.py` and `test_inverted_grade.py`, which
  use gsm8k's id as a stand-in.
- **Commits:** `b245a641b` feat (rows, ids, pins, CHANGELOG); `df6cdda42` docs (two records).
- **Gates:** 1,640 passed in the 38 Engine test files naming gsm8k or winogrande, 23 passed in
  `test_fidelity_check.py`; ruff and pyright clean on the six touched Python files;
  `fidelity_check.py` → 94 fresh, 0 stale, 0 no record, 0 orphan.
- **New ids:** gsm8k `075954bfd63059e0` → `7eebba58799a2f22`; winogrande `4eb60a70db7518d6` →
  `3f2af135ba8bad37`. Neither had a leaderboard entry on prod or dev (checked 2026-11-10).
- **Deviations:**
  - Both records read `unverified`, not the `comparable-to-inspect` the ticket expected. Capture
    folds inspect's system message into the user turn (the plugin-wide rule DROP already follows),
    so the text matches on every Case but the role differs. Only a paired Candidate run can size
    that. Owner was told before the move and chose to proceed once no leaderboard entries were confirmed.
  - winogrande keeps a second open deviation: inspect_evals' Task sets `max_tokens=64` and our
    Benchmark has no way to apply a Task's generation settings. Owner chose a separate ticket to
    build that mechanism.
  - Digests were sealed on macOS, not linux/amd64: both Benchmarks are text-only, so no picture
    re-encode can make them platform-bound; the CI image build re-checks them.
  - Built on OME-1858's PR 3 branch, the only home of the two records; that stack merged into main
    the same day, so main was merged in and the PR targets main.
- **Owner-verify:** CI green; post the two id moves to the team.
