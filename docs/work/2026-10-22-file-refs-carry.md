---
ticket: unfiled   # sub-issue A of OME-1543 (plan §5); filed at PR-open, after #1450 and #1482 merge
stack: url4
status: in_progress
started: 2026-10-22
finished:
---

# file-refs-carry — carry run attachments through url4 runs, fan-out, reduce, iteration and retries

## Intent

Implement the url4 half (sub-issue A, plan §3) of `OME-1543` (epic `OME-1529`): a run-scoped,
ordered, immutable `attachments[]` side-channel bound by `run()`, fixed at run start from the AST's
file refs (no string scanning, F2), with a per-run file cache so each file is fetched and verified
once, and carried to every in-process endpoint call via `Request.attachments`. Owner-approved
2026-10-22 to start coding before #1450 (spec) merges; branch is based on `origin/OME-1539-url4-file-refs`
(#1482) and rebased once it merges. No PR until #1450 and #1482 merge.

Plan: `docs/plan/2026-10-21-OME-1543-file-refs-carry-plan.md` (branch `file-refs-carry-plan`).
Spec: #1450 `docs/spec/2026-10-16-OME-1535-file-input-execution.md` (F1/F1b/F2/F3, D1–D6).

## Planned changes

- `packages/url4/src/url4/dag/attachments.py` (new: carrier, run cache, collector, resolver)
- `packages/url4/src/url4/dag/_run.py` (`attachments=` kwarg; bind/reset; run-start resolution)
- `packages/url4/src/url4/dag/nodes/blob.py` (read the run cache)
- `packages/url4/src/url4/dag/_lowering.py` (§2.9 `$x*(…)` over a blob binding)
- `packages/url4/src/url4/peer/_dispatch.py` (`Request.attachments`, `call_endpoint`)
- `packages/url4/src/url4/__init__.py`, `packages/url4/ARCHITECTURE.md` (U6)
- Tests (new/appended): `tests/unit/test_attachments.py`, `tests/unit/test_attachment_propagation.py`,
  `tests/unit/test_server.py` (new functions), `tests/unit/test_public_api.py` (new function)

## Test plan

- Plan §3 U1–U6 test lists, in order, RED first. U3b (`https://` sources) waits for `OME-1544`.

## Acceptance

- A ref fanned out to 3 members reaches every member and the reducer; text-only DAGs byte-identical.
- `run_gates.py url4` green without `--skip-append-only`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
