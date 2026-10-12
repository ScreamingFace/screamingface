---
ticket: OME-1574
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# sad-raw-host-prefetch — the benchmark image build fetches the SAD dataset from GitHub's raw host

## Intent

The benchmark image build replays each Task-replay Imported Benchmark's task function in a
clean room with empty caches. SAD's loader (inspect_evals) fetches its five zips through
GitHub's contents API, anonymously; five SAD Benchmarks each fetch all five, so one build makes
25 API calls, and GitHub allows 60 anonymous calls an hour per IP address. A CI runner that
shares its IP address gets HTTP 403 and the build fails. This unit fills the replay's empty
cache with the same five zips from GitHub's raw host before the task function runs; upstream's
`download()` then finds checksum-matching files and never calls the API.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/case_source_prefetch.py` (new) —
  the SAD prefetch (addresses, checksums and paths imported from
  `inspect_evals.sad.download_data`) and a package → prefetch map.
- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py` — the replay
  child runs the prefetch for its Task before resolving the task function and before the
  Case Source recorder installs; one helper names the replay's inspect_evals cache.

## Test plan

- `tests/unit/inspect/test_sad_prefetch.py` (new, no network):
  - a SAD Task prefetches exactly five raw-host URLs at the pinned commit, with the same
    checksums and the same cache-relative paths upstream's own `_ensure_downloaded` requests;
  - a non-SAD Task (and a package that merely starts with "sad") prefetches nothing;
  - the replay child prefetches into its own inspect_evals cache before resolving the task.

## Acceptance

- A SAD replay makes no call to api.github.com; the bytes are verified against upstream's
  pinned sha256 by inspect's own `download()`.
- No Benchmark revision, Case Digest or provenance block changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the `docs/tasks/` mirror.
- **Commits:** see the PR (`fix(screamingface-engine): fetch the SAD zips from GitHub's raw host`).
- **Gates:** `test_sad_prefetch.py` 3 passed; `test_task_replay.py` 36 passed; ruff check +
  format clean on touched files; pyright 0 errors on touched files both extra-less and with the
  inspect extra. Full suite left to the pre-push hook and CI.
- **Manual check (free):** prefetched into a temp cache from the raw host (all five sha256
  match), then ran upstream's `_ensure_downloaded` with that cache and every httpx send
  blocked: zero network calls.
- **Deviations:** none. The provenance block still names the API address upstream's loader
  asks for (the recorder installs after the prefetch); the sha256 pin is unchanged.
- **Owner-verify:** the next benchmark image build passes with the five SAD Benchmarks
  prepared (no HTTP 403).
