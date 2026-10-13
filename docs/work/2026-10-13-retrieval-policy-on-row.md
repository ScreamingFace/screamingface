---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# retrieval-policy-on-row — let a Benchmark row declare its retrieval policy

## Intent

OME-1527 requirement R13, Work order #17. draco moves to a local Task next (Work order #18), and
its exam says "web search on, seven domains banned". The plugin lane hard-coded the Candidate
call to `web_search=false`, so no row could say that. This unit lets a row declare a retrieval
policy (a policy id plus the banned domains). The row's Candidate call then carries it, the
existing Candidate adapter applies it as the ceiling no nested call can widen (the same path
the hand-built draco takes), and the id plus sorted domains join the Benchmark Revision. The
Task still never runs tools: capture's refusal stays, because the search loop is the
Candidate's.

## Planned changes

- `single_shot.py`: `RetrievalPolicyDeclaration` (checked when declared: id shape, non-empty
  bare domains, stored sorted); the factory hashes it into the revision when set; the Candidate
  call takes it in place of the hard-coded `False`; the INVARIANT comment rewritten.
- `benchmarks.py`: `BenchmarkSpec.retrieval_policy`, passed to the factory.
- `importer.py` / `task_replay_rows.py`: `--retrieval-policy ID` plus repeatable
  `--retrieval-excluded-domain DOMAIN`, refused before any replay when malformed; the generated
  row writes the declaration only when set.

## Test plan

- A row without a policy sends `web_search=false` and nothing else (byte-for-byte as before).
- A row with one sends `web_search=true&web_search_exclude=<sorted domains>`.
- Through the real Candidate adapter and a mock gateway: the banned domains reach a model call
  that named none; without a policy, a call asking to search is held off.
- Revision moves only when set; domain order and case do not move it; another domain does.
- Malformed declarations refused (blank or spaced id, newline, empty list, path, wildcard, bare
  string); importer flags land on the row; malformed flags refused before any replay.

## Acceptance

- No existing row sets the field; `test_published_revisions.py` passes untouched.
- No pre-existing test edited (append-only).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; new test file `tests/unit/inspect/test_retrieval_policy_on_row.py`;
  two tests appended to `tests/unit/inspect/test_importer_command.py`. No pre-existing test
  edited, so no test-change approval entry.
- **Commits:** feat(screamingface-engine): let a Benchmark row declare its retrieval policy
- **Gates:** relevant files only, with the inspect extra: 324 passed
  (`test_retrieval_policy_on_row.py`, `test_importer_command.py`, `test_published_revisions.py`,
  `test_inspect_single_shot.py`, `test_task_replay_rows.py`, `test_import_replay.py`,
  `test_list_target.py`, `test_local_task_contracteval.py`, `test_judged_benchmark_assembly.py`,
  `test_whole_run_metric.py`, `test_native_web_search.py`, `test_benchmark_foundation.py`,
  `test_attempt_egress.py`); without the extra the inspect files skip and the rest pass. ruff
  check + format clean; extra-less pyright 0 errors on touched files; append-only check passes
  against upstream/main. Full gate runs in the pre-push hook + CI.
- **Deviations:** "unknown policy id" has no list to check against (no registry of policy ids
  exists; draco's id is a label a score cites), so the id is checked for shape only. An empty
  domain list is refused, following draco's own build rule.

## Owner-verify

- Nothing to press for this unit: no row sets the field yet. The first paid run that searches
  through it is draco's, after Work order #18 merges.
