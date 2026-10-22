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

Status: **partial — U1, U2, U3 (1–15 + item 9), U4, U5, U6 docs done; U3b and the U6 root
export held for owner decisions** (below). No PR (owner: not until #1450 and #1482 merge).

- **Actual files:** as planned, except `url4/__init__.py` (U6 export held) and
  `peer/_http.py` (added: the HTTP ingress detaches the run binding). Collector and
  resolver helpers live in `dag/attachments.py`; the async resolution is in `dag/_run.py`
  (it needs `BlobRefNode`, which imports `dag/attachments.py`).
- **Commits:** `9ce3189da` U1+U2 carrier/cache; `b793c4036` U3 run-start resolution;
  `e46f45658` U3 item 9 `$x*(…)`; `f9a1ce692` U4 propagation pins; `cbfd4aa5a` U5
  `Request.attachments`; `500c51a88` U6 docs.
- **Gates:** `run_gates.py url4 --base origin/OME-1539-url4-file-refs` ALL GREEN;
  `run_gates.py screamingface-engine` ALL GREEN (not touched; regression smoke).
- **Deviations:**
  1. Branch rebased once onto the force-pushed #1482 head `a7e051ed0` (was `703e3105d`);
     that head carries `OME-1544` (#1521) so the guard codes exist.
  2. Append-only is checked against the #1482 head (the branch base), as the dispatch
     instructed, because U2.8 was adjusted when the cache value type became `CachedBlob`
     (a `None` media type must survive for D4; `Attachment` would turn it into octet-stream).
  3. Iteration bodies and call contexts are raw text in the AST; the collector parses them as
     source-lists (as the lowering does) and skips a segment that does not parse (prose, or a
     template that only parses after row substitution). A ref that only appears after
     substitution is not in the list; its node fetches on a cache miss.
  4. U3.16 is written as `test_bound_blob_in_collection_position_is_read_as_text`: a
     `x=<blob>` binding is a contributing source (ABNF, `OME-534`), so under "a `src=` value
     in the AST is an attachment" it IS attached. Owner question Q-A below.
  5. U4 golden was recorded by running the DAG on the #1482 base in a scratch worktree.
  6. U5 adds `detached_run_files()` at the HTTP ingress: an in-process ASGI transport shares
     the caller's context, so without it a served request would see the caller's files.
- **Open for the owner:**
  - **Q-A (U3.16):** should a blob bound by name (`x=…`) and read only as `$x*(…)` be
    attached? The binding contributes its ref text to the payload, so the code attaches it.
  - **Q-B (U3b):** `src=` is erased by the grammar (`(src=https://a)` and `(https://a)` give the
    same `Url`), so "only an `https://` value in a `src=` binding" cannot be told apart in the
    AST. Eagerly fetching every scalar `https://` source at run start changes text-only DAGs
    (D5: a failed `;optional` text source would fail the run). Needs a grammar marker or a
    rule decision; plus Q7(b) write-through.
  - **Q-C (U6):** exporting `Attachment` and `current_attachments` from `url4` needs the
    `EXPORTS` ratchet in `tests/unit/test_hygiene_ratchets.py` bumped (59 → 61), a prior test.
  - **Q-D:** #1450's head says Case parts "travel in the v2 envelope instead" of url4
    attachments; the plan's `run(attachments=…)` (U2) is kept as the engine's injection point.
