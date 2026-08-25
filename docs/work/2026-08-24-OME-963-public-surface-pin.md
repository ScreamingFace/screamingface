---
ticket: OME-963
stack: screamingface
status: done
started: 2026-08-24
finished: 2026-08-24
---

# OME-963 — Fail CI when the public SDK surface changes

## Intent

Pin the public import surface of `packages/screamingface` in a checked-in, human-readable
snapshot so any rename/removal/re-signing of a public name turns CI red. The red is a
communication trigger ("write the changelog and tell users"), not a bug — requirement R6
of OME-956. Regenerating the snapshot is a deliberate human act, never automatic in CI.

## Planned changes

- `packages/screamingface/tests/test_public_surface.py` — new snapshot test (standalone,
  no e2e-harness dependency): builds the live surface (top-level `__all__`, signatures of
  public callables, public methods/properties of public classes, enum members, pinned
  submodule namespaces incl. `screamingface.report`), diffs it against the snapshot,
  and on mismatch prints a unified diff + the exact regeneration command
  (`UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`).
- `packages/screamingface/tests/public_surface_snapshot.json` — the checked-in snapshot
  (sorted keys, indented, one entry per line) generated from the CURRENT surface.
- `packages/screamingface/tests/test_public_interface.py` — superseded and removed; its
  still-valuable assertions (legacy-alias absence, module-level delegation/lazy default
  client behavior, notebook-extra leanness) move into `test_public_surface.py` so one
  file stays the single authority on the public surface. No two competing pins.

## Test plan

- RED first: run the new test without a snapshot file → clear failure telling the reader
  how to generate it.
- Mutation check: temporarily alter a public signature in-process → unified diff appears
  and names the changed entry; revert.
- Regeneration path: `UPDATE_SURFACE_SNAPSHOT=1` writes the snapshot and still fails
  loudly (regeneration is never a silent green).
- Green: full package suite passes with the committed snapshot.
- Invariant encoded in the docstring: the public surface moves only with a deliberate
  snapshot update + changelog entry.

## Acceptance

- Snapshot test green on this branch with the committed snapshot.
- Removing/renaming/re-signing any public callable or class method turns the test red
  with a readable diff; internal refactors stay green.
- Exactly one public-surface authority file remains.
- Full package test suite green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned —
  `packages/screamingface/tests/test_public_surface.py` (new, 8 tests),
  `packages/screamingface/tests/public_surface_snapshot.json` (new, 1108 lines /
  ~44 KB, generated from the current surface), and
  `packages/screamingface/tests/test_public_interface.py` deleted (superseded; all
  still-valuable assertions moved into the new file so exactly one surface authority
  remains). Review round added: `src/screamingface/benchmarks.py`,
  `src/screamingface/leaderboards.py`, `src/screamingface/models.py` (one-line
  `from __future__ import annotations` each, closing the internal-path leak).
- **Commits:** uncommitted — pending local owner review
- **Gates:** `uv run pytest` → 1066 passed, 1 skipped; `ruff check` + `ruff format
  --check` + `pyright` clean on the new test. RED verified twice (missing snapshot;
  mutated public parameter name → unified diff naming the entry + regeneration
  instructions). Regeneration run (`UPDATE_SURFACE_SNAPSHOT=1`) writes the snapshot
  and deliberately still fails so it can never pass as a green build.
- **Deviations:** none in the initial pass. Owner review round (needs changes) applied:
  - Internal-path leak in pinned signatures confirmed and fixed — but at different
    files than the review named: `discovery.py`/`leaderboard.py` already had the
    future import; the leak came from the facade modules `benchmarks.py`,
    `leaderboards.py`, `models.py` (no `from __future__ import annotations`), which
    now carry it. Snapshot regenerated; zero `screamingface.<module>.` paths remain,
    and `_signature_of` now REJECTS (loudly, naming the callable) any rendered
    signature embedding an internal module path or a `0x...` memory address, so
    neither leak can be re-committed silently. Docstring claim corrected to match.
  - `UPDATE_SURFACE_SNAPSHOT` now honors only `1`/`true` — `=0` compares, never
    updates (verified by running with `=0`).
  - Package-module check tightened to `screamingface` / `screamingface.` exactly, so
    sibling packages like `screamingface_engine` can never match.
  - `catches_as` now pins ALL public exception ancestors including stdlib ones
    (decision documented in code: e.g. `EvaluationWarning` staying a `UserWarning`
    is what keeps users' warning filters working); only `BaseException`/`object`
    and private internals are skipped.
  - A broken `__all__` entry now fails with a curated message naming the module and
    entry instead of a bare AttributeError.
  Snapshot regenerated after these changes (catches_as + clean facade signatures).
- **Merge-order note:** sibling branch OME-959 adds a refusal-kind field to the public
  case-result contract in parallel. Whichever branch merges second must regenerate the
  snapshot (`UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py`)
  and record the interface change in the changelog — that red is the tripwire working
  as designed.
