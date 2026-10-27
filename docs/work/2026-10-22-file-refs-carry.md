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

Status: **done for url4 sub-issue A — U1–U6 incl. U3b and the U6 root export** after the owner
decisions Q-A..Q-D (Linear `OME-1543` comment "Owner decisions (Sergey, 2026-10-22)"). No PR
(owner: not until #1450 and #1482 merge).

### Owner decisions applied (2026-10-22)

- **Q-A:** no change. A blob bound by name (`x=…`) and read only as `$x*(…)` stays attached
  (the binding is a contributing source, spec F2); `test_bound_blob_in_collection_position_is_read_as_text`
  already pins it.
- **Q-B (U3b):** `https://` sources stay lazy. `WebFetchNode` (scalar position, inside a run)
  re-fetches a body the text path refused as not-text through `fetch_bytes`, hashes it into the
  run cache (by URL and digest) and fills its source-position slot (`RunFiles.slots`, built by
  `scan_sources` at run start); dedup by digest with blob refs and Case parts; payload = URL text.
  Text bodies, `;optional`, and `x.source_*` refusals (text or bytes fetch) are unchanged.
  Collection position (and outside a run) keeps `unsupported_content_type`. Commit `5ee0debb1`.
- **Q-C (U6):** `url4.Attachment` and `url4.current_attachments` exported; EXPORTS ratchet
  59 → 61 pinned in `.claude/test-change-approvals/OME-1543.json`. Commit `be0eb4daf`.
- **Q-D:** `run(attachments=…)` kept as the engine's injection point; no url4 change.

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
  7. U3b fetches a non-text `https://` body twice (text path refuses, then `fetch_bytes`): the
     engine may not import `io.media.is_text_media_type` (layering), and routing text bodies
     through the bytes path would risk changing their decoding. Only binaries, which failed
     before, pay the second GET.
  8. U3b is lazy (Q-B), so an `https://` attachment is visible to the calls that run after its
     fetch (every call that reads the source), not to an unrelated sibling that ran earlier.
     Concurrent first reads of one URL are not single-flighted (plan U3b test 5 is cache-hit
     only); persisting the bytes to the engine's tenant+run store stays engine work (Q7).
  9. The approval pin names branch `file-refs-carry`; it must be updated at the PR-open rename.
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

## Round 2026-10-27 — spec review round 6 (pre-materialize + freeze, static manifest, caps): BLOCKED

**Intent.** Bring the branch to #1450 at `96727acc8` (F1b "pre-materialize, then freeze", static
source manifest / `x.source_not_static`, one record per `(URL, accept)` with required winning,
bare-Content-Type classification, per-run caps `x.attachments_too_many` / `x.attachments_too_large`).

**Done.**
- Merged the #1482 head `a405c41e8` (C6 `x.remote_node_unsupported`) into this branch (merge, no
  rebase): `e4871c0f6`. Conflicts resolved conservatively: `dag/nodes/blob.py` and
  `dag/_lowering.py` keep this branch's version (the #1482 side equals the pre-rebase content
  already here, ours is a superset); `core/errors.py` and the OME-1539 ledger take both sides;
  `dag/_descriptor.py` takes the #1482 `RemoteFetchNode` import. No test file conflicted.
  `run_gates.py url4` ALL GATES GREEN (append-only vs HEAD) on the merged tree.

**Blocked (no code written).** The normative F1b text cannot be met without editing prior
tests that `.claude/test-change-approvals/OME-1543.json` does not name:
1. `tests/unit/test_https_attachments.py::test_text_https_body_is_not_attached_and_payload_is_unchanged`
   asserts `io.byte_targets == []` for a text `https://` source. F1b: every https source goes
   through ONE `fetch_bytes` at admission that both classifies and yields the body ("no second
   fetch"), so a text source is fetched as bytes.
2. `tests/unit/test_https_attachments.py::test_guard_refusal_on_the_text_fetch_surfaces_as_today`
   asserts `io.byte_targets == []` and a refusal from the TEXT fetch; under F1b the refusal must
   come from the admission bytes fetch.
3. `tests/unit/test_dag.py::test_run_all_success_path_returns_row_results` (and the other
   `StaticIOLayer` tests with an `https://` source and no `media_types`: 35 test files name an
   https URL with `StaticIOLayer`, 6 set `media_types`): F1b reads a missing Content-Type as
   `unsupported_content_type`, a terminal failure that fails the run for a required source.
   Today these sources are text (the #1478 text path reads an absent type as text).
4. The module INVARIANT "https sources stay lazy (Q-B)" in `dag/attachments.py`,
   `dag/nodes/web_attach.py` and `tests/unit/test_https_attachments.py` is superseded by F1b
   (round 5/6); the test-module docstring is part of a prior test file.
Likely also affected (not verified by running): tests whose https targets carry `$` templates
(`x.source_not_static`), and fetch-order/concurrency tests whose https fetches would move ahead
of the first model call.

**Deviations / open questions (for the owner).**
- Approve a test-change manifest for the tests above (give the `StaticIOLayer` fixtures
  `text/plain` / `application/json` media types; change the two `byte_targets == []`
  assertions to "exactly one bytes fetch"), or
- narrow F1b so a source with no Content-Type keeps the text path's "absent = text" reading in
  pre-materialization (a spec change in #1450, contradicting its current wording), or
- scope pre-materialization to a run that names at least one attachment-capable source (also a
  spec change; the current text says every https source).
