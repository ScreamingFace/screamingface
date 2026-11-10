---
ticket: OME-1861
stack: screamingface-engine
status: done
started: 2026-11-10
finished: 2026-11-10
---

# attempt-call-collect — a failed Candidate call fails only its own Attempt

## Intent

A Benchmark with Attempts asks each Case N times. Today a Candidate call that errors in any one
Attempt (the model's token budget spent before any text, a reasoning-only reply, a provider or
gateway error) is raised as a url4 error out of the whole Case, so the Attempts that did answer
are thrown away and the Case scores 0. Under the mean fold (OME-1856, the ZeroBench rule) 4 right
tries + 1 token-cap failure scores 0.0 where inspect_evals and the authors score 0.8. OME-1458
accepted this as a known limitation at one Attempt's cost; the mean fold makes it cost N times
more. This unit collects a failed call inside its own Attempt, so the Attempt arrives at the
marking room as a failed Attempt carrying the error's own code, and the fold already decides:
an empty answer (`EMPTY_ANSWER_CODES`) is a wrong try, every other error leaves the mean.
Spec: `docs/spec/2026-11-10-attempt-call-collect.md`. Plan: `docs/plan/2026-11-10-attempt-call-collect.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/protocol.py`: `_attempted_case`
  wraps each Attempt's execution in url4's `iterate(["$item"], on_error="collect")`, binds the
  Case's position once at Case level (`case_position` = `$index`) and `_numbered` rewrites the
  Candidate Invocation's `case_index` to read that binding (inside the wrapper `$index` is 0).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/graded_answer.py`: the
  case-attempts route unwraps each Attempt's one-row list (the wrapper's output) and keeps a
  collected error row as the Attempt's row.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/benchmark_aggregation.py`:
  no code change expected; an error row for a known Case already becomes a failed Case carrying
  the error's code (the missing-case rung, OME-1390). Verified by test, changed only if needed.
- `attempt_fold.py` (OME-1856): comment only, the two codes now reach the fold.
- Spec amendment to `docs/spec/2026-10-07-OME-1458-attempts-per-case.md` §4 and F4; the new spec.
- Mirror `docs/tasks/`, this ledger.

## Test plan

- `tests/unit/test_case_attempts_protocol.py` (appended): a three-Attempt Case whose second
  Candidate call raises `model_token_cap` keeps Attempts 1 and 3, files Attempt 2 failed with
  that code; the Case's position header is unchanged inside the wrapper (0, 1 over two Cases);
  a gateway error on one Attempt is a failed Attempt with that code; all N calls failing is a
  failed Case led by Attempt 1's code; the one-Attempt expression is byte-identical (existing
  pinned hashes).
- `tests/unit/test_attempt_fold.py` and `tests/unit/inspect/test_attempts_mean_fold.py`: the
  end-to-end numbers through the real aggregate: 4 right + 1 token cap → 0.8 under `mean`, 1.0
  under `any`; 4 right + 1 gateway error → 1.0 under `mean` (4 of 4) and `any`.
- `tests/unit/test_case_attempts_contract.py`: every Attempts Benchmark still asks N; the
  rendered expression of an Attempts Benchmark reads `$index` once (the Case-level binding).
- Lanes: `test_case_attempts_protocol.py`, `test_case_attempts_contract.py`,
  `test_attempt_fold.py`, `test_benchmark_aggregation.py`, `test_benchmark_protocol.py`,
  `test_attempt_egress.py`, `test_capture_replay_proof.py`; with the inspect extra
  `tests/unit/inspect/test_attempts_mean_fold.py`, `test_imported_attempts.py`,
  `test_local_task_arc_agi_2.py`.

## Acceptance

- 4 right tries + 1 token-cap failure scores 0.8 under the mean fold and 1.0 under any-of-N.
- A gateway error in one Attempt leaves that Attempt out: 4 right + 1 gateway error = 1.0.
- A one-Attempt Benchmark's url4 is byte-identical (pinned hashes green, unmodified).
- The Candidate still sees its Case position (k of N) inside every Attempt.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `protocol.py`: `_attempted_case` binds `case_position` (`$index`) beside the Attempts and wraps each Attempt in `iterate(["$item"], on_error="collect")`; new `_positioned` rewrites the Candidate Invocation's `case_index` to read the binding; module and function docstrings updated. `graded_answer.py`: `_case_attempts_route` unwraps each Attempt's one-row list via `_attempt_row`. `benchmark_aggregation.py`: unchanged, as predicted: an error row for a known Case already files as a failed Attempt by the error's code (pinned end to end). `attempt_fold.py`: reach comment only. Tests appended in `test_case_attempts_protocol.py` (a stand-in Candidate whose call errors on named Attempts, through the real url4 node: the kept Attempts, the code on the failed one, every call failing, the Case position inside every Attempt), `test_attempt_fold.py` (4 right + 1 token cap → 0.8 mean / 1.0 any; 4 right + 1 gateway error → 1.0 both, through the real aggregate), `test_case_attempts_contract.py` (one `$index`, one `$case_position` per Candidate Invocation). Prior test moved: `test_local_task_arc_agi_2.py`'s byte-for-byte url4 pin (294a4844… → 16e583d1…), which exists to flag exactly this change; approval JSON pins it. Specs: new `docs/spec/2026-11-10-attempt-call-collect.md`; OME-1458 §4 bullet lifted and F4 amended; OME-1856 D15 reach note updated.
- **Commits:** 0c388ddeb fix(screamingface-engine): let a failed Candidate call fail only its own Attempt; the filing commit (mirror, approval JSON, this line).
- **Gates:** extra-less `test_case_attempts_protocol.py test_attempt_fold.py test_case_attempts_contract.py test_benchmark_protocol.py test_benchmark_aggregation.py test_attempt_egress.py test_capture_replay_proof.py`: 168 passed. With the inspect extra, those plus `tests/unit/inspect/test_attempts_mean_fold.py test_imported_attempts.py test_local_task_arc_agi_2.py test_benchmark_fingerprints.py test_failure_policy_revisions.py`: 380 passed (ARC-AGI-2's published revision unchanged; only its url4 pin moved). ruff, ruff format, pyright clean on the touched Python files. `test_benchmark_protocol.py::test_the_public_catalogue_publishes_exactly_the_registered_benchmarks` fails with the inspect extra on the base branch too (catalogue order; not this unit; the extra-less CI lane is the gate). Spikes (deleted): a per-Attempt collect hands the join route `[{"error": {code}}]` and keeps the others; Case positions measured (0, 1) plain, (0, 0) wrapped, (0, 1) with the binding.
- **Deviations:** none from the plan. One design fact learned: the wrapper's output is a one-row list, so the join route unwraps it (spec D3) instead of accepting the envelope directly.
- **Owner-verify:** the re-pinned ARC-AGI-2 url4 hash (a prior test moved by design, flagged on the PR); the ZeroBench paid smoke (OME-1855) exercises the path live once #1706 lands.
