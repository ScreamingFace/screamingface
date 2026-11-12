---
ticket: OME-1543
stack: url4
status: in_review
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

Status: **in review as PR #1587 (targets main, not a draft)**. url4 sub-issue A, U1–U6, after
the owner decisions Q-A..Q-D (Linear `OME-1543` comment "Owner decisions (Sergey, 2026-10-22)").
Q-B's lazy `https://` design below was replaced in round 7 by run-start materialization; the
per-round entries further down are the current record. `finished:` is filled at merge.

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

## Round 2026-10-27 — module-size ratchet: pure refactor of four url4 modules: DONE

**Intent.** Four url4 modules failed `packages/url4/scripts/check_module_size.py` (it is not in
the card's `url4` gates; run separately). Split each by reason to change into a private
submodule, re-export every moved name from the original module, no behaviour change, no test edit.

**Done.**
| Module (before → after, cap) | Moved to | Commit |
|---|---|---|
| `dag/_run.py` 336 → 234 (271) | `dag/_run_files.py` (run-start file resolution), `dag/_run_observe.py` (RunStarted/RunFinished bookkeeping) | `a5212b598` |
| `dag/nodes/fetch.py` 307 → 245 (290) | `dag/nodes/struct.py` (`StructNode` + decoding helpers) | `b8bc987a9` |
| `peer/_dispatch.py` 224 → 201 (214) | `peer/_reassemble.py` (`reassemble`, `_TRANSPORT_PARAMS`) | `38964a0a7` |
| `dag/_lowering.py` 654 → 622 (640) | `dag/_iteration_refs.py` (`_ROW_NAMES`, `_body_intent_refs`, `_body_ref_edges`) | `8cc91b413` |

- `run()` and `_to_node` stay in `dag/_run.py`: `test_iteration.py` spies `compile_expression`
  on `url4.dag._run`, so the outer compile must still look it up there.
- Re-exports are redundant-alias imports (`from m import x as x`), so every prior
  `url4.dag._run.*` / `url4.dag.nodes.fetch.*` / `url4.peer._dispatch.*` / `url4.dag._lowering.*`
  path still resolves.
- Gates: `check_module_size.py` all within baseline; `run_gates.py url4` ALL GREEN (append-only
  vs HEAD and vs `02771b601`, no test file changed); `run_gates.py screamingface-engine` ALL GREEN
  (not touched; regression smoke).

**Deviations / open questions.**
- The new submodules are not added to the ratchet's `BASELINE` (conservative: the gate script
  is untouched). Capping them would stop regrowth; owner call.
- `StructNode.__module__` is now `url4.dag.nodes.struct` (likewise for the other moved names);
  no test or doc depends on it.

## Round 2026-10-27 — spec review round 7 (opt-in attachment sources, reachability manifest): DONE (open questions below)

**Intent.** Bring the branch to #1450 at `357ce4199` (F1b "Scope of attachments", round 7): an
`https://` source is an **attachment source** iff every range of its `;accept=` is in the
attachment set (`image/*`, `image/png`, `image/jpeg`, `image/gif`, `image/webp`,
`application/pdf`); every other source is a text source and keeps today's lazy,
per-occurrence semantics. Attachment sources are pre-materialized before the first model call
from a reachability-aware manifest (non-model collection inputs resolved first and reused), one
flight per identity `(URL, accept, ;optional, ;t=, ;retry=)`, classified by bare Content-Type,
listed in manifest preorder, frozen; per-run caps 20 entries / 8,000,000 bytes.

**Planned changes.**
- `dag/attachment_sources.py` (new): attachment set, `;accept=` classification, identity,
  guard-policy decoding shared with `_descriptor.py`, response classification.
- `dag/_materialize.py` (new): collection pre-resolution (reuse memo), identity
  materialization (one flight, guard policy), caps.
- `dag/attachments.py`: identity slots in the source scan (preorder), collection guards,
  manifest outcomes and the prefetch memo on `RunFiles`.
- `dag/_run_files.py`, `dag/_descriptor.py`, `dag/nodes/fetch.py`, `dag/nodes/_shared.py`,
  `core/errors.py` (`x.source_not_static`, `x.attachments_too_many`, `x.attachments_too_large`),
  `peer/_http.py` (proposed statuses 422 / 413 / 413).
- Tests (new): `tests/unit/test_attachment_sources_round7.py`.

**Test plan.** The round-7 conformance cases, RED first: empty collection → no I/O; duplicate text
occurrences with differing `;t=`/`;retry=`/`;optional` as today; no-header / XML / `+json` / YAML /
charset / Latin-1 text sources unchanged; wrong or missing type on an attachment source →
`unsupported_content_type`; same URL with and without a media `;accept=` independent; identical
identities one flight; reversed completion order → preorder; caps; model-derived →
`x.source_not_static`. Fake IO only, no network/DNS, no new `sleep(` calls.

**Done.** One commit on `file-refs-carry` (see `git log`; message
`feat(url4): pre-materialize opt-in https attachment sources before the first model call`).
- `dag/attachment_sources.py` (new): attachment ranges/types, `identity_of`, `classify` (bare
  Content-Type, no sniffing, fail-closed on a comma), `guard_policy` (moved from `_descriptor.py`,
  re-exported there as `_guard_options` / `_annotation_number`), `not_static`.
- `dag/source_scan.py` (new, split from `dag/attachments.py` by reason to change; every name
  re-exported from `attachments`): the scan now records attachment-source occurrences in preorder
  with the collection guards they are conditional on, and slots each identity in source order.
- `dag/_materialize.py` (new): static check (`x.source_not_static`) before any I/O; collection
  pre-resolution outer-first, stopping at an empty one, results kept in a one-shot replay memo
  (`RunFiles.take_prefetched`, consulted by `nodes/_shared._fetch`); one guarded `fetch_bytes`
  flight per reachable identity, concurrently; `check_caps` (20 / 8,000,000) over the whole list.
- `dag/_run_files.py`: `_run_start` returns `RunStart` (slots, cache, manifest, replay memo);
  the unused `_run_files` tuple wrapper and its `_run` re-export were removed (no caller in the repo).
- `dag/attachments.py`: `RunFiles.manifest` / `prefetched`; an identity slot is its own dedup key.
- `dag/nodes/fetch.py` + `web_attach.materialized_attachment`: an attachment source reads its
  URL text from the frozen manifest and never fetches; an omitted `;optional` one re-raises its
  code as permanent (dropped by its guard, no retry, no re-fetch); unknown in a run →
  `x.source_not_static`; outside a run → today's text path.
- `core/errors.py` + `peer/_http.py`: `x.source_not_static` 422, `x.attachments_too_many` 413,
  `x.attachments_too_large` 413 (proposed statuses, §4).
- Tests: `tests/unit/test_attachment_sources_round7.py`, 53 tests (all round-7 conformance cases
  plus admission/collection shapes). No prior test edited; no new `sleep(` (the reversed-order
  test uses events).
- **Gates:** `run_gates.py url4` ALL GREEN (append-only vs HEAD); `check_module_size.py` green;
  `run_gates.py screamingface-engine` ALL GREEN (not touched; regression smoke).

**Conservative readings (design forks under 95%).** Owner decisions 2026-10-27: 1 → resolved by
decision A (Q-B dropped); 2–3 → superseded by round 8 (decision B: no `image/*`, exact type);
4, 5, 6, 7 → **owner-CONFIRMED (decision D)**; 8 → stands (the URL text is the payload).
1. **U3b vs round 7.** The branch's Q-B lazy path still attaches a non-text body of a TEXT
   source (no media `;accept=`) after the first model call. Round 7 says text sources are never
   attached and byte-identical to main (where that body is `unsupported_content_type`). Removing
   U3b changes these prior tests, which `.claude/test-change-approvals/OME-1543.json` does not
   list, so U3b is kept unchanged: `tests/unit/test_https_attachments.py::`
   `test_non_text_https_body_is_attached_once_at_its_source_position`,
   `test_https_body_with_a_blob_refs_digest_is_attached_once`,
   `test_case_attachments_precede_an_https_attachment`,
   `test_guard_refusal_on_the_bytes_fetch_fails_the_run_unchanged[*]` (4 params).
2. `image/*` is in the attachment range set but the exec-value grammar (§4.2) refuses `*`, and a
   comma splits sources, so `;accept=image/*` and multi-range values cannot be authored today.
3. Response types are the concrete `image/png|jpeg|gif|webp` and `application/pdf` only;
   `image/*` matches those four, never e.g. `image/svg+xml`.
4. An attachment source under a model-derived collection (a processed group, a call, a remote
   expression, a nested iteration, or a binding to one) is `x.source_not_static`, even though its
   URL is literal (URLs never substitute in this grammar), because its reachability is only known
   after a model call.
5. A collection admission cannot resolve without running the body (a row reference `$item`, a
   blob ref, holdings, a templated relative path) counts as reachable (may fetch for an empty one).
6. A pre-built `Graph`/node target has no AST and so no manifest: its attachment sources are
   `x.source_not_static`; so is one in a nested `run()` or spawned text the outer scan never saw.
7. Caps apply to every top-level run (Case attachments + blob refs + https attachments), also
   a run with no https attachment source.
8. The attachment source contributes its URL text to the payload (as U3b did); an omitted
   optional one is logged `WARN` with its code via `ExecutionContext.log`.

## Round 2026-10-27b — round-7 review findings (admission guard policy, slot preorder): DONE (finding 3 BLOCKED on the owner)

**Intent.** Fix two blocking review findings on the round-7 commit; the third (Q-B vs round 7)
needs an owner decision and prior-test approvals, so it is reported, not changed.
1. `_materialize._fetched_rows` resolved a collection with one bare fetch (its descriptor's
   `;retry=`/`;t=`/`;optional` stripped by `_unwrap`), so a transient failure read as zero rows,
   the body later ran and its attachment source raised `x.source_not_static` mid-run.
2. `source_scan._add_attachment` slotted an identity at its first occurrence in the AST, reachable
   or not; F1b places it at its first REACHABLE occurrence in manifest preorder.

**Planned changes.** `dag/_materialize.py` (collection admission under its own guard policy,
final outcome replayed as permanent; reachable occurrence positions), `dag/source_scan.py`
(per-occurrence slot markers; bindings keep their descriptor), `dag/_run_files.py` (resolve the
markers after reachability). Tests (new file): `tests/unit/test_attachment_sources_review.py`.

**Test plan.** RED first: transient collection failure with `;retry=2` still fetches the
attachment once before the first model call and attaches it to every call; an `;optional`
collection that fails makes no attachment I/O and no `x.source_not_static`; a collection with
`;accept=` is fetched once; slot order `[JPG, IMG]` when IMG's first occurrence is unreachable,
`[IMG, JPG]` when it is reachable.

**Done.** One commit on `file-refs-carry` (`fix(url4): admit attachment-gating collections under
their own guard policy and slot identities at their first reachable occurrence`).
- `dag/_materialize.py`: `_unwrap` returns the collection's outermost descriptor; `_fetched_rows`
  resolves a fetched collection through `GuardNode` with `guard_policy(ann)` (bare fetch when
  unannotated) and the descriptor's `;accept=` (so the replay key matches the lowered node); the
  FINAL outcome is recorded in the replay memo, a failure copied as permanent (an omitted
  `;optional` one as a permanent `ResolutionError` with its code), so execution never re-spends
  the policy. `materialize` returns `Admission(outcomes, prefetched, first_reachable)`.
  AIDEV-NOTE corrected (an annotated collection is resolved, not assumed reachable).
- `dag/source_scan.py`: `OccurrenceSlot(index)` per attachment-source occurrence in `order`;
  `reachable_order` places each identity at its first reachable occurrence (blob-ref / URL slots
  keep their positions); `_bindings` keeps a named descriptor (not its value) so `$xs*(…)`
  admission sees the binding's policy.
- `dag/_run_files.py`: slots built from `reachable_order(...)` after admission.
- Tests (new): `tests/unit/test_attachment_sources_review.py`, 9 tests (the reviewer's repro
  included). No prior test edited.
- **Gates:** `run_gates.py url4` ALL GREEN (append-only vs HEAD); `check_module_size.py` green.

**Finding 3 (Q-B vs round 7) — BLOCKED, owner decision.** Not changed. Removing the Q-B lazy path
(`attach_web_body`, `cached_web_attachment`, `RunFiles.fetched`, the string URL slots in
`source_scan._add_leaf`) changes prior tests that `OME-1543.json` does not approve:
`tests/unit/test_https_attachments.py::test_non_text_https_body_is_attached_once_at_its_source_position`,
`::test_https_body_with_a_blob_refs_digest_is_attached_once`,
`::test_case_attachments_precede_an_https_attachment`,
`::test_guard_refusal_on_the_bytes_fetch_fails_the_run_unchanged[*]`. If the owner keeps Q-B
instead, the spec must change and the caps + freeze must cover lazily attached bodies (today
`check_caps` runs only at run start, so 25 Q-B bodies attach with no `x.attachments_too_many`).

**Conservative readings (round 7b).** **Owner-CONFIRMED 2026-10-27 (decision D).**
1. A collection whose guarded admission fails finally is NOT reachable (no attachment I/O) and
   execution replays that failure as permanent — the run fails (or the optional binding is
   omitted) exactly as admission decided, never with a later successful retry.
2. Nested descriptors on a collection: the outermost one's policy and `;accept=` apply.

## Round 2026-10-27c — owner decisions A–E (drop Q-B, round 8 narrowing, row targets, caps): DONE (C in round 2026-10-27d)

**Intent.** Apply the owner decisions of 2026-10-27 (main session, AskUserQuestion) and #1450 round 8
(`4a020cc39`):
- **A.** Drop Q-B: a text source (no exact media `;accept=`) is never attached, whatever its body.
  Remove `attach_web_body`, `cached_web_attachment`, `RunFiles.fetched` / `attach_fetched`, the
  string URL slots in `source_scan._add_leaf`. Owner-approved changes to
  `tests/unit/test_https_attachments.py` (four tests + module docstring), pinned in
  `.claude/test-change-approvals/OME-1543.json`.
- **B.** Round 8: an attachment source's `;accept=` is EXACTLY one lower-case type from
  `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `application/pdf`; the response bare type must
  EQUAL it, else `unsupported_content_type`. No `image/*`, no lists.
- **C.** (Revised by the owner later the same day, see round 2026-10-27d: row-derived attachment
  URLs are DEFERRED; v1 attachment targets are literal.)
- **D.** Mark the round-7/7b conservative readings owner-confirmed.
- **E.** Investigate the security review's cap items in `_run_files.py` / `_materialize.py`.

**Planned changes.** `dag/attachment_sources.py` (exact-type classification), `dag/attachments.py`,
`dag/source_scan.py`, `dag/nodes/web_attach.py`, `dag/nodes/fetch.py`, `dag/_run_files.py`,
`dag/_materialize.py` (caps on every adding path, before the first model call). Tests: new
`tests/unit/test_attachment_sources_round8.py`; approved edits to `test_https_attachments.py`; this
unit's own round-7 tests updated where round 8 narrows them (listed in the outcome).

**Test plan.** RED first: text source with a non-text body → `unsupported_content_type`, no bytes
fetch, no attachment; `;accept=IMAGE/PNG` / `image/*` / a list → text source; `;accept=image/png`
answered `image/jpeg` → `unsupported_content_type`; cap breach refused before every remaining flight
/ blob verification; no attachment can be added after run start.

**Done.**
- **A (Q-B dropped).** Removed `attach_web_body`, `cached_web_attachment` (`nodes/web_attach.py`
  keeps only `materialized_attachment`), the Q-B branch of `WebFetchNode.resolve`,
  `RunFiles.fetched` / `attach_fetched` and string slots (`RunFiles.slots` is
  `Attachment | AttachmentIdentity`), the URL slots of `source_scan._add_leaf` (`_Found.urls`).
  A text source with a non-text body is today's `unsupported_content_type`, never fetched as bytes.
- **B (round 8).** `attachment_sources.is_attachment_accept`: `accept in ATTACHMENT_TYPES` (exact,
  lower-case, one type); `classify`: bare lower-cased response type must EQUAL `identity.accept`.
  Removed `ATTACHMENT_RANGES`, `accept_ranges`, `AttachmentIdentity.ranges`, `_matches`.
- **E (caps).** New `dag/_caps.py` (`CapBudget`, `check_caps`, the two constants; re-exported from
  `_materialize`). `_run_start` order: `refuse_remote` → `check_static` (no I/O) → `CapBudget(case)`
  → `expect` attached blob keys → blob verification (bytes charged as each lands) →
  `materialize` (collections; `expect` reachable REQUIRED identities before any flight; each
  flight's bytes charged OUTSIDE its guard, so a breach cancels in-flight siblings and an
  `;optional` guard cannot swallow it) → final `check_caps`. `RunFiles.manifest` is a
  `MappingProxyType`; `slots` a tuple: nothing can add to `attachments[]` after run start.
- `ARCHITECTURE.md` files bullet rewritten (no Q-B, exact type, caps on every path).
- **Tests added** (`tests/unit/test_attachment_sources_round8.py`, 38 cases):
  `test_text_source_with_a_non_text_body_fails_as_today_and_is_never_fetched_as_bytes`,
  `test_optional_text_source_with_a_non_text_body_is_dropped_not_attached`,
  `test_text_source_next_to_an_attachment_source_adds_nothing_after_run_start`,
  `test_each_attachment_type_alone_opts_a_source_in[5]`,
  `test_anything_but_exactly_one_lower_case_attachment_type_is_a_text_source[12]`,
  `test_upper_case_accept_is_a_text_source_on_the_wire`,
  `test_response_type_equal_to_the_accept_type_classifies[4]`,
  `test_response_type_not_equal_to_the_accept_type_is_unsupported[6]`,
  `test_too_many_required_attachments_are_refused_before_any_attachment_fetch`,
  `test_case_and_blob_refs_count_before_any_attachment_fetch`,
  `test_an_omitted_optional_identity_does_not_count_toward_the_entry_cap`,
  `test_byte_cap_breach_cancels_the_flights_still_in_progress`,
  `test_case_bytes_count_before_any_attachment_fetch_is_spent`,
  `test_the_bound_list_cannot_grow_after_the_run_starts`,
  `test_many_non_text_text_sources_can_no_longer_bypass_the_caps`.
- **Tests changed, owner-approved (decision A)**, pinned in `OME-1543.json` (`amendments`;
  base = this branch's HEAD `37722dce5` blob): `tests/unit/test_https_attachments.py` module
  docstring, `::test_non_text_https_body_is_attached_once_at_its_source_position`,
  `::test_https_body_with_a_blob_refs_digest_is_attached_once` (now: blob refs dedupe by digest,
  equal identities share one attachment, blob vs identity never merged — round 7 rule — so
  `(IMG, IMG)`), `::test_case_attachments_precede_an_https_attachment`,
  `::test_guard_refusal_on_the_bytes_fetch_fails_the_run_unchanged[*4]`.
- **Tests changed, this unit's own round-7 tests (decision B)**:
  `tests/unit/test_attachment_sources_round7.py` module docstring;
  `::test_image_wildcard_range_is_an_attachment_range_but_not_authorable_today` RENAMED to
  `::test_image_wildcard_is_not_an_attachment_type_and_not_authorable` (asserts `image/*` is not
  an attachment type and classifies nothing); `::test_accept_with_any_non_attachment_range_is_a_text_source`
  (`"IMAGE/PNG, application/pdf"` now a text source; adds `application/pdf` positive).
  No other prior test changed (`tests/unit/test_attachments.py::test_run_file_cache_is_discarded_when_run_exits`
  writes to `RunFiles.cache`, so the cache stays a mutable dict; it never feeds `attachments[]`).

**E — security findings.**
1. `_run_files.py` cap bypass: **real** — `check_caps` ran once at run start over
   `RunFiles(slots, {}, {}, outcomes)`, i.e. with `fetched` empty, while Q-B's `attach_fetched`
   appended non-text text-source bodies after the first model call, uncapped and unfrozen (25 such
   bodies attached with no `x.attachments_too_many`). Fixed by removing Q-B (decision A) and
   freezing the manifest; regression `test_many_non_text_text_sources_can_no_longer_bypass_the_caps`
   and `test_the_bound_list_cannot_grow_after_the_run_starts`.
2. `_materialize.py` cap placement: **real (resource exhaustion, not a list overflow)** — caps were
   checked only after EVERY flight and blob verification completed, so a run naming many
   required attachment sources downloaded all of them (each up to the guard's per-fetch cap)
   before being refused. Fixed with `CapBudget` (count before I/O, bytes as they land, cancel on
   breach); regressions `test_too_many_required_attachments_are_refused_before_any_attachment_fetch`,
   `test_byte_cap_breach_cancels_the_flights_still_in_progress`,
   `test_case_bytes_count_before_any_attachment_fetch_is_spent`.

**C — superseded by round 2026-10-27d (owner deferred row-derived attachment URLs).** The
grammar finding stands: an absolute `Url` never substitutes, and `src=$item;accept=image/png` is a
`VarRef` source whose value is the row text.

**Deviations.**
- Refusal precedence moved: blob refs are verified BEFORE collection admission and attachment
  flights (they were after), so the entry cap and the byte cap see Case → blob refs → flights in
  that order and a breach stops the network flights. `x.remote_blob_unsupported` and
  `x.source_not_static` still precede any I/O. No prior test pinned the old order.
- Append-only: vs the merge-base with `origin/main` (`506c09178`) — the files this unit added are
  "A" there; the run vs HEAD flags only `test_attachment_sources_round7.py` (this unit's own
  tests, owner-allowed under decision B), with `test_https_attachments.py` passing on its pin.
- **Gates:** `run_gates.py url4 --base 506c09178` (merge-base with `origin/main`) ALL GREEN;
  `check_module_size.py` all within baseline; `run_gates.py screamingface-engine` ALL GREEN (not
  touched; regression smoke).

## Round 2026-10-27d — decision C revised: row-derived attachment URLs DEFERRED: DONE

**Intent.** Owner (Sergey, 2026-10-27, via the coordinator): row-derived attachment URLs are
deferred (follow-up improvement idea "Allow row-derived attachment URLs in url4"). v1 attachment
sources have a literal URL and a literal `;accept=`. A source that carries an exact attachment
`;accept=` but whose target is a variable (`src=$item;accept=image/png`, `src=$u;accept=…`) must
not silently read as text: refuse it with `x.source_not_static` before any fetch. A literal
attachment source in an iteration body stays one identity (fetched once if any row is reached, not
at all over an empty collection). No row-derived admission exists in the code (none was written).

**Planned / done.**
- `dag/attachment_sources.py`: `non_literal_attachment(node)` — the target text of a `VarRef`
  source, or a `$`-templated relative path, carrying an exact attachment `;accept=`; `not_static`
  message names "literal URL" instead of only a model output.
- `dag/source_scan.py`: `SourceScan.non_literal` collected in scalar position.
- `dag/_run_files.py`: refused right after `refuse_remote`, before `check_static` and any I/O.
- Tests added (`tests/unit/test_attachment_sources_round8.py`):
  `test_variable_source_with_a_media_accept_is_not_static_before_any_fetch[4]` (row `$item` with
  image/png; named row source with `;optional` and application/pdf; `$u` bound to literal text;
  `$u` bound to a fetched https source), `test_variable_source_with_a_non_media_accept_stays_a_text_value`,
  `test_literal_attachment_source_in_an_iteration_body_is_one_identity`,
  `test_literal_attachment_source_over_an_empty_collection_is_never_fetched`. RED confirmed for the
  four refusals; the other three already held. No prior test changed (no test on `origin/main` or on
  this branch writes a variable or templated relative source with an attachment `;accept=`).

**Readings (conservative).**
1. A `$`-templated RELATIVE path with an attachment `;accept=` (`src=/files/$name;accept=image/png`)
   is treated as substituted, so refused; a literal absolute URL containing `$` is literal (absolute
   URLs never substitute) and is a normal attachment source.
2. The refusal is static: it applies to every such occurrence the scan sees in scalar position,
   reachable or not (even under an empty collection), because it is a v1 authoring error.
3. A `;optional` on such a source does not soften the refusal (it is not a fetch failure).
4. A pre-built `Graph` has no AST, so the scan cannot see such a source; there it reads as text
   as before (same limitation as reading 6 of round 7).

**Gates.** `run_gates.py url4 --base 506c09178` ALL GREEN (append-only also green vs HEAD: only
new test functions); `check_module_size.py` within baseline; `run_gates.py screamingface-engine`
ALL GREEN (not touched; regression smoke).

## Round 2026-10-28 — reconcile onto the rebased #1482 head: DONE

Owner-approved (Sergey, 2026-10-28) so the OME-1543 PR can open right after #1478 merges.
`file-refs-carry` (head `1e7e7cd31`) had merged an older #1482 head (`a405c41e8`, merge
`e4871c0f6`); #1482 (`OME-1539-url4-file-refs`) is now `963e55fa4`, stacked on #1478
(`OME-1538-url4-bytes-fetch` `0ca51beb7`, on main `ca7738b16` incl. #1555).

**Done.**
- New branch `OME-1543-file-refs-carry` from `963e55fa4`; replayed with `cherry-pick -x` the 22
  OME-1543 commits (`d0f3b66d0` … `1e7e7cd31`): reachable from `1e7e7cd31`, not from `a405c41e8`,
  minus the merge `e4871c0f6` and minus the five pre-rebase #1482 commits (`796b05551`,
  `b208b35d9`, `850dfc5fd`, `fd9979b08`, `a7e051ed0`).
- No conflicts. The merge `e4871c0f6` carried no conflict-resolution hunks (empty `--cc`), and the
  only file both the replay and the upstream rebase touch is `dag/nodes/blob.py` (auto-merged).
- `.claude/test-change-approvals/OME-1543.json`: `branch` → `OME-1543-file-refs-carry`. Blob pins
  unchanged and still exact (`test_hygiene_ratchets.py` base `d34dfb69` = `963e55fa4` = origin/main,
  approved `c2492021` = HEAD; `test_https_attachments.py` approved `36b98bfd` = HEAD).
- `file-refs-carry` kept untouched as the backup (not deleted, not force-pushed).

**Gates.** `run_gates.py url4 --base origin/main` ALL GREEN (approved OME-1543 transition on
`test_hygiene_ratchets.py`; append-only green); `check_module_size.py` and
`check_suppressions.py` within baseline; `run_gates.py screamingface-engine --base origin/main`
ALL GREEN.

## Round 2026-10-28 — local e2e bugs (node `fetch_bytes`, binary `[data]` files): DONE

Owner-approved (Sergey, 2026-10-28). Two bugs from a local end-to-end run.

**Intent.**
1. `Url4Node` has no `fetch_bytes`, so on a node every https attachment source is refused by
   `dag/_materialize.py` with a misleading `unsupported_content_type` before the destination guard
   runs. Give the node a binary-safe `fetch_bytes` (absolute → outbound `fetch_bytes`, through
   its guard; relative → the node's own dispatch, bytes-safe for data routes), and make the
   "io has no binary-safe port" case an accurate typed error.
2. `url4 serve` `[data]` files are read with `read_text(utf-8)`: a binary file (a
   `/blob/sha256/<hex>` route) raises `UnicodeDecodeError` → 500 `internal_error`. Read file data
   as bytes on the binary path; on the text path a non-UTF-8 file is a typed permanent error.

**Planned changes.** `peer/server.py` + `peer/_dispatch.py` (node `fetch_bytes`, bytes data
dispatch), `cli/_serve.py` (file provider with a bytes read; typed decode error),
`dag/_materialize.py` (code of the no-bytes-port refusal); new tests
`tests/unit/test_node_bytes_fetch.py`.

**Test plan.** RED first: a `build_node(ServeConfig)` node with a fake guarded transport attaches
an `https` source with `;accept=image/png` (guard consulted: resolver sees the host; a metadata
address is refused with `x.source_destination_blocked`); a binary `[data]` file serves a verified
`/blob/sha256/<hex>` ref in-process; the text read of it is a typed permanent error, not 500.

**Acceptance.** `run_gates.py url4 --base origin/main` green; module-size + suppressions green;
engine gate green.

**Outcome.**
- New `peer/_bytes.py`: `Url4Node.fetch_bytes` (bound as a class attribute in `peer/server.py`).
  Absolute target → the outbound layer's own `fetch_bytes` (its destination guard, size cap and
  deadline apply); an outbound without the port → `unsupported_mode` (permanent), never
  text-encoded. Relative target → the node's dispatch order; a data route whose provider has
  `read_bytes` (`SupportsReadBytes`) is read byte-exact, everything else is its text UTF-8 encoded.
- New `cli/_files.py`: `FileData` (text `__call__` + `read_bytes`) for `[data]` file routes;
  every file text read (data, holdings, identities) maps `UnicodeDecodeError` to
  `unsupported_content_type` (permanent, C8) instead of a 500 `internal_error`.
- `dag/_materialize.py`: the no-bytes-port refusal is now `unsupported_mode` (was the misleading
  `unsupported_content_type`).
- Splits forced by `check_module_size.py` (by reason to change, caps untouched).
- Tests: new `tests/unit/test_node_bytes_fetch.py` (12, RED first).

**Deviations.**
- Code choice: §4 of the OME-1535 spec has no code for "the io has no binary-safe port"; used
  `unsupported_mode` (501), the existing permanent code the repo already uses for the analogous
  missing-capability case (relative code pointer on an io without `SupportsCode`, `dag/nodes/code.py`).
  Spec §4 should list it (owner/Kevin follow-up).
- One branch-own test changed (not on `origin/main`, not in the manifest's pinned blobs):
  `test_attachment_sources_round7.py::test_attachment_source_on_an_adapter_without_bytes_fetch_is_unsupported`
  now expects `unsupported_mode` — the owner-directed fix of exactly that code.
- Out of scope, noted: over HTTP the node still serves data routes through the text port, so a
  remote GET of a binary `[data]` file is now a typed 4xx `unsupported_content_type`, not bytes.

**Gates.** `run_gates.py url4 --base origin/main` ALL GREEN (append-only green);
`check_module_size.py` within caps; `check_suppressions.py` 3/3 baseline;
`run_gates.py screamingface-engine --base origin/main` ALL GREEN.

## Round 2026-11-02 — e2e F3 (`@` in a call context): DONE

**Outcome.** `815a6b9ad` — `dag/source_scan.py` decides a context's holdings pass-through on its
parsed segments (`holds_holdings_ref`: `SelfRef` / `IdentityRef`, nested call contexts and
iteration bodies included; an unparseable segment counts only if it holds `@`). The
`@`-in-URL repro now fetches and attaches; real `@` / `@identity` contexts keep today's verbatim
behaviour. Tests: new `tests/unit/test_context_holdings_scan.py` (11). Gates:
`run_gates.py url4 --base origin/OME-1539-url4-file-refs` ALL GREEN; `check_module_size.py`
within caps. `dag/_lowering.py:235` is unchanged (conservative raw-text fallback; the context
text rides as the F1b text part). **Stopped:** "an unparseable segment raises" contradicts the
pinned `test_attachments.py::test_a_prose_or_holdings_context_contributes_no_refs` and deviation
3 above (prose and template segments contribute nothing). Awaiting an owner decision.

**Owner decision (Sergey, 2026-11-02): "raise only with an opt-in".** `e2770a162` — the source
scan records an unparseable call-context segment (`SourceScan.malformed`) only when (a) the same
context carries an attachment opt-in (a parsed `src=…;accept=<attachment type>`, literal or
not), or (b) the segment itself contains `src=` / `;accept=`; `_run_files._run_start` refuses it
via `source_scan.refuse_malformed` with permanent `malformed_source` (the code
`attachment_sources.guard_policy` already raises for a bad descriptor; no new code) BEFORE any
I/O, first among the run-start refusals. No extra parse: the existing per-segment parse returns
its failures. Prose alone stays prose (pinned `test_a_prose_or_holdings_context_contributes_no_refs`
unedited); holdings contexts and iteration bodies (templates, deviation 3) record nothing.
`test_context_holdings_scan.py::test_an_unparseable_segment_without_an_at_sign_does_not_hide_the_others`
still holds unedited — it asserts the scan's occurrences; the refusal fires at run start.
Tests: new `tests/unit/test_context_malformed_segment.py` (14; MockTransport + resolver fail on
any request). Merged `origin/OME-1539-url4-file-refs` (02907ccfc, #1482) normally. Gates:
`run_gates.py url4 --base origin/OME-1539-url4-file-refs` ALL GREEN (2735 passed, 17 xfailed);
`check_module_size.py` within caps (`dag/_context.py` untouched at 455; `source_scan.py` 379).

## Round 2026-11-03 — security review: redact attachment URL query strings in logs and errors: DONE

**Intent.** A push security review flagged `dag/_materialize.py` writing the full attachment URL
into the run log (`optional attachment source … omitted`) and an internal `RuntimeError`. A
signed URL's query (`X-Amz-Signature`, `token`, `sig`) would leak. Text-only fix; no behaviour
change.

**Planned.** One display helper `display_url(raw)` (scheme, userinfo redacted to `***`, host,
port, path; query → `?<redacted>`, fragment → `#<redacted>`; never raises, malformed →
fixed placeholder) in `url4/core/url_display.py` — NOT next to `redact_userinfo` in `io/_source_policy.py`,
because `test_layering` forbids `dag` importing `url4.io` beyond `io.layer`/`io.idempotency`.
Apply at every PR-added site that interpolates an attachment/source URL into a log line or an
exception: `_materialize.py` (check_static, collection-admission RuntimeError, WARN log,
flight RuntimeError, fetch_bytes UNSUPPORTED_MODE), `attachment_sources.py` (classify,
guard-value ParseError), `nodes/web_attach.py` (not_static), `_run_files.py` (not_static of a
non-literal target), `peer/_bytes.py` (`no_bytes_port`). No existing test pins a URL in any of
these messages (grepped).

**Test plan.** New `tests/unit/test_attachment_url_redaction.py`: helper table (signed URL,
fragment, userinfo, plain URL, relative path, malformed inputs never raise); per site a signed
URL whose token never appears in the WARN log events/attributes, the raised error text, or
`caplog`, while scheme/host/path still show.

**Outcome.** `url4/core/url_display.py` (`display_url`, `UNPARSEABLE`; public module name
because `test_hygiene_ratchets` caps private cross-layer imports). Sites changed:
`_materialize.py` (WARN log, both `stored nothing` RuntimeErrors, fetch_bytes
UNSUPPORTED_MODE), `attachment_sources.py` (`classify`, guard-value ParseError via `_shown`,
`not_static` now takes the raw target and redacts it itself), callers `_materialize.check_static`,
`nodes/web_attach.py`, `_run_files.py`, and `peer/_bytes.no_bytes_port`. New
`tests/unit/test_attachment_url_redaction.py` (23). No prior test edited. Gates:
`run_gates.py url4 --base origin/OME-1539-url4-file-refs` ALL GREEN; `check_module_size.py`
within baseline (`dag/_context.py` untouched at 455).
**Deviations / not changed.** (1) Helper lives in `core`, not `io/_source_policy.py` (layering).
(2) Out of this PR's diff and left as-is: `io/http.py` (`GET {url!r} failed…`, deadline,
redirect limit) and `io/media.py` (`{target!r} has Content-Type…`) still interpolate the full
URL; an omitted optional source's `ResolutionError(outcome.message)` can carry them. Follow-up.
(3) `source_scan.refuse_malformed` echoes a malformed call-context segment and
`refuse_remote` a `url4://` blob ref — text/refs, not fetched URLs; unchanged.

## Amendment 2026-11-03 — shared live byte budget (push security review "resource-cap-defeat")

**Finding.** `materialize` runs every attachment flight concurrently (`gather_or_cancel`, up to
20); each `fetch_bytes` was bounded only by the guard's 20 MiB per-response cap, and
`CapBudget.charge` ran only after a body had fully landed, so one run could download and hold about
20 × 20 MiB before the 8,000,000-byte cap refused it. Owner decision (Sergey, 2026-11-03): **one
shared live budget**.

**Change.** io half in #1482 (`FetchRequest.max_bytes` / `on_chunk`, honoured by the guarded
transport per decoded piece of every hop, an injected client's read, and non-streaming adapters
after the read), merged here normally. This PR:
- `dag/_caps.py` — `CapBudget` gains `charge_bytes(key, n)` (live draw, refuses once settled +
  in-flight bytes pass the cap), `release(key)` (give-back), `remaining()` (cap − SETTLED bytes,
  the flight's `max_bytes`), `raise_if_refused()`; one `threading.RLock`; refusal is sticky (every
  later draw is refused). `charge` still counts once per key and now settles the key's live bytes;
  `check_caps` stays the authoritative final check.
- `dag/_materialize.py` — each attempt of `_AttachmentFetchNode` releases first (a retry starts
  over), sends `max_bytes=budget.remaining()` and `on_chunk=partial(budget.charge_bytes, identity)`,
  and releases at once on any failure or cancellation (before a sibling draws again).
  `_flight` re-raises a refusal an `;optional` guard swallowed (`raise_if_refused`).
- `ARCHITECTURE.md` — one sentence on the live budget.

**Design notes.** `max_bytes` uses settled bytes only: in-flight bytes may be refunded, so a
ceiling counting them could raise `x.source_too_large` (a source failure) for a body the run has
room for; the live total is enforced chunk by chunk. A redirect hop's body draws from the budget
too (httpx holds it) — conservative.

**Tests (append-only, new file).** `tests/unit/test_attachment_live_budget.py` (11): 20 concurrent
1 MiB flights via `HttpIOLayer` + counting mock transport refused `attachments_too_large`
(permanent), bytes read 9,175,040 ≤ 8,000,000 + 20 × 65,536 = 9,310,720 (before the fix:
20,971,520), 0 of 20 bodies read to the end, all closed, no model call; a single 20 MiB body
refused after 8,060,928 bytes (before: 20,971,520); 4,000,000 + 4,000,000 passes, 4,000,000 +
4,000,001 fails; a 9 MB `;optional` breach still refuses the run; a transient mid-body failure
gives its bytes back before `;retry=1`; an `;optional` source that streamed 7 MB then failed
consumes no budget (5 MB required source then lands); `max_bytes` = cap − Case bytes; budget unit
tests (settle once per key, exact boundary, release, sticky refusal). Existing cap tests
(rounds 7/8) unedited and green.

**Gates.** `run_gates.py url4 --base origin/OME-1539-url4-file-refs` ALL GATES GREEN;
`check_module_size.py` within baseline (`dag/_context.py` untouched at 455/455);
`check_suppressions.py` 3/3; hygiene ratchets green.

## Round 2026-11-04 — HupBaHa CHANGES_REQUESTED on `c9230710b` (six findings): DONE

Merged `origin/main` normally first (no conflicts). Owner decisions (Sergey, 2026-11-04) per
finding; each lands as its own commit with an append-only test file.

**Planned.**
1. Local/relative blob reads draw from the shared live `CapBudget` (`max_bytes` / `on_chunk`
   through `BlobRefNode.verified`, the text-only fallback, the node's relative bytes dispatch and
   a chunked `[data]` file read). Repro: two 7 MB blobs refused without holding 14 MB.
2. One shared collection-shape resolver (`dag/_collection_shape.py`) decides model vs model-free
   for both the scan and admission: follows `$a -> $b -> …` chains and field paths with cycle
   protection; verified blob collections are parsed from the run-start cache before
   reachability and slot order. Repros: `$xs.rows` from a model result, `$zs -> $ys -> $xs`,
   a blob collection holding `[]` sends no nested image.
3. `run(Graph | DagNode)`: FAIL CLOSED — any attachment-capable source in a pre-built graph
   (attachment opt-in, blob ref, `url4://` blob ref, malformed opt-in context, non-literal
   attachment target) is refused before any I/O; text-only graphs unchanged.
4. Remote-node calls (`url4://` remote expressions) are found by the scan and refused
   (`x.remote_node_unsupported`) before any run-start I/O, without consuming a client's hop.
5. Only `https://` is an attachment source; `http://` stays on the text path.
6. After concurrent flights / blob reads fail, a sticky byte-cap refusal is re-raised so
   `x.attachments_too_large` always wins.

**Outcome.** One commit per finding (tests append-only, all new files; no prior test edited):

| # | Commit | Change | Tests |
|---|---|---|---|
| 5 | `6513a68c6` | `attachment_sources.identity_of`: `https://` only | `test_attachment_http_text_path.py` (5) |
| 6 | `a9cd4a45b` | `_caps.gather_charged`: after a failed gather, a sticky refusal is re-raised; used for flights and run-start blob reads | `test_attachment_cap_refusal_wins.py` (4); the blob-read race test is in `test_blob_live_budget.py` (committed with 1) |
| 1 | `246bb49c7` | `_run_files._verify` reads attached blobs with `max_bytes=remaining()` / `on_chunk=charge_bytes`, gives back on failure; `BlobRefNode.verified` passes both (text fallback too); peer relative bytes honour the request; `[data]` files read in 64 KiB pieces (`FileData.read_chunks`, `SupportsReadChunks`) | `test_blob_live_budget.py` (13) |
| 4 | `132821f8d` | scan records every `url4://` remote call; `_run_start` prechecks them (`remote_nodes.precheck_remote_nodes`, read-only) before any I/O when the run has run-start I/O | `test_remote_node_before_attachment_io.py` (13) |
| 2 | `a58bceb7a` | `dag/_collection_shape.resolve_collection`: one resolver for `check_static` and admission; follows every `$name` hop + path, cycle-safe; mirrors execution (a `$name` collection is the binding text with each hop's path, no media type; only a direct unpathed `$x` bound to a blob ref reads the body); blob collections read from the verified run-start cache | `test_attachment_reachability_resolver.py` (21) |
| 3 | `3b41f9aea` | `dag/_graph_admission.refuse_prebuilt` (fail closed, before any I/O); non-literal attachment targets lower to `NotStaticNode` | `test_prebuilt_graph_fail_closed.py` (33) |
| — | (this commit) | edge/error paths of 1–3 | `test_attachment_round9_edges.py` (6) |

**Shortcuts and limits (stated plainly).**
- F1: ~~a blob whose digest is already counted (a Case attachment) is read without the budget
  hooks~~ CLOSED in the follow-up below. A text-only io, a whole-bytes `[data]` provider and a node's
  endpoint/eval bytes cannot stream: they are charged (and `max_bytes`-checked) right after the
  read, as `io.media.read_whole` already does, so one such body is held before the refusal.
- F2: still conservatively reachable (fetched, attached): a row reference (`$item`), holdings, a
  templated source, a bound inline group, a cycle. A `;optional` collection binding that fails is
  unreachable at admission; execution would then substitute `$xs` verbatim — if that ever runs a
  body, its attachment source is not in the manifest and fails `x.source_not_static` (closed).
- F3: an attachment opt-in or non-literal target in a pre-built graph keeps `x.source_not_static`
  (the code two existing tests pin since round 7), now before any I/O; blob refs, malformed contexts
  and opt-ins hidden in kept text are `malformed_source` (a `url4://` blob ref
  `x.remote_blob_unsupported`). The `NotStaticNode` lowering also refuses `src=$v;accept=<type>`
  for an executor that bypasses `run()` (it read as text before) — owner decision C.
- F4: gated on run-start I/O, so a text-only run keeps the execution-time refusal unchanged.
  ~~A `url4://` reduce PROCESSOR is refused only when the reduce runs~~ CLOSED in the follow-up
  below (a Form-3 computed processor is still checked when it resolves: its value is unknown
  before it is evaluated).

**Gates.** `run_gates.py url4 --base origin/main` and `run_gates.py screamingface-engine --base
origin/main`: ALL GATES GREEN (exit 0; append-only check green on both). `check_module_size.py`:
all capped modules within baseline (`source_scan.py` 417, `_materialize.py` 397 lines).

### Follow-up 2026-11-04 — owner: close both disclosed gaps before re-review: DONE

1. **`url4://` reduce processor.** `processor.remote_processor_hop` reads a LITERAL `url4://`
   processor (`run(processor=…)` or a node's `default_processor`, i.e. `run_ctx.processor`);
   `_run_files._precheck_remote` adds it to the same `precheck_remote_nodes` call as the AST's
   remote expressions, before any run-start I/O. `_check_remote_processor` uses the same parser.
   It is refused even when the expression has no reduce (fail closed). A Form-3 expression
   processor is only known once evaluated and keeps its resolve-time check.
2. **Case-attachment blob reads.** `CapBudget` keeps each counted key's size; `charge_bytes` on a
   counted key draws only the bytes BEYOND that size (an honest re-read adds nothing — the list
   dedups it — so `test_a_blob_equal_to_a_case_attachment_is_not_counted_twice` stays green
   unedited), `charge` on a counted key gives its live bytes back, and `ceiling(key)` =
   `remaining()` + its counted size is the read's `max_bytes`. `_verify` no longer bypasses the
   hooks. Measured: Case 4 MB + 4 MB with the store serving 9 MB per digest → refused
   `x.attachments_too_large` after 62 + 1 chunks = 4,128,768 bytes streamed (before: each read ran
   to the io's own cap). Residual: an honest re-read of a Case digest still holds one more copy of
   that body while it is verified (the run's list does not grow).

Tests (new file, append-only): `tests/unit/test_review_gaps_closed.py` (10).

### Review round 10 (HupBaHa, 2026-11-05, head `0b562f450`) — owner decisions Sergey 2026-11-05: DONE

**Intent.** Close the three remaining High findings, append-only tests, each repro RED first.

**Planned changes.**
1. Whole-body reads. (a) A blob ref whose digest equals a verified Case attachment reuses the Case
   bytes, no store read (`_run_files._verify`). (b) A peer data provider that cannot stream draws
   its DECLARED size from the run budget before the read (`FetchRequest.on_declared`,
   `CapBudget.reserve`, `peer/_bytes.serve_data_bytes`); unknown or over budget →
   `x.attachments_too_large`, no read.
2. Templated model-derived collections. `_collection_shape`: a templated `RelUrl` whose `$name`
   resolves to a model is `MODEL` (→ `x.source_not_static`, zero I/O); a binding cycle is marked
   unreachable (admission fetches nothing), kind kept `UNKNOWN`.
3. Form-3 processor expressions. `_run_files._precheck_remote` parses an expression-valued
   processor and adds its structural remote calls to the pre-I/O precheck.

**Test plan.** New file `tests/unit/test_review_round10.py`: 2 × 7,000,000-byte synchronized
whole-body providers peak ≤ cap; unknown size refused with no read; lying size refused; honest
declared size passes; 8 MB Case + same-digest store body → no store read; the templated repro
makes zero fetches and refuses; a cycle fetches nothing; the Form-3 processor repro makes zero
fetches.

**Acceptance.** Both gate runs green (exit 0); no prior test edited.

**Outcome.**
- 1(b) DONE. `FetchRequest.on_declared` (io/layer.py); `CapBudget.reserve` draws a declared size
  through `charge_bytes`, refuses an undeclared one stickily; `peer/_bytes.serve_data_bytes`
  reserves before `read_bytes()` / a callable text provider and draws only bytes past the declared
  size after; a plain `str` provider's size is known. `_verify` passes
  `on_declared=partial(budget.reserve, key)`. Repro: 2 × 7,000,000 B synchronized → refused,
  peak 7,000,000 ≤ 8,000,000 (was 14,000,000).
- 2 DONE. `_template_kind`: a `RelUrl` template whose `$name` resolves to `MODEL` is `MODEL`
  (→ `x.source_not_static`, zero I/O); `CollectionShape.cycle` makes admission treat a cycle as
  unreachable (kind stays `UNKNOWN`, so `test_a_binding_cycle_terminates_as_unknown` is untouched).
  No other UNKNOWN-reachable case changed.
- 3 DONE. `_processor_expression_calls`: a Form-3 processor is parsed and `scan_sources`'
  `remote_nodes` join the pre-I/O precheck.
- 1(a) STOPPED. Reusing the Case bytes (trial) breaks exactly one prior test,
  `test_review_gaps_closed.py::test_case_attachment_blobs_served_past_the_cap_are_refused_within_a_chunk`
  (it asserts the oversized store copy IS read and refused); needs an owner call to amend it.
- Tests: `tests/unit/test_review_round10.py` (15, new; no prior test edited).
- Gates: `run_gates.py url4` and `run_gates.py screamingface-engine` (`--base origin/main`) exit 0;
  `check_module_size.py` exit 0.
- Deviations: a whole-body provider that declares no size (incl. a callable text provider) is now
  refused for a run's attached blob read (fail closed, by decision).

**Follow-up 2026-11-05 (owner: amend the 1(a) test; security review of `567f33e57`).**
- 1(a) DONE. `_run_files._verify` answers a ref whose digest is a Case attachment's from the
  Case bytes (no store read, one resident copy). Owner-approved amendment of
  `test_case_attachment_blobs_served_past_the_cap_are_refused_within_a_chunk` (now: never read,
  one copy, within the cap), recorded in `.claude/test-change-approvals/OME-1543.json`.
- DoS DONE. `_template_kind` re-walked bindings per path (`seen` per branch): 2^n on a doubling
  chain (n=18 → 1.26 s). Replaced by `_TemplateWalk`: one shared visited set (each binding
  followed once, linear) plus `MAX_TEMPLATE_STEPS = 4096`, past which the collection is
  model-derived (fails closed `x.source_not_static`). n=3000 → 4 ms.
- Tests appended to `test_review_round10.py`: 1(a) repro (2 params), deep doubling chain, dense
  fan-out, long template, step-budget fail-closed.

**Review round 11 (HupBaHa 2026-11-05T14:16:42Z) — findings 2 and 3; finding 1 pending owner.**

**Intent.** Admission's collection scope mirrors execution's wiring (`_wiring._build_slots`,
`_lowering._build_ctx_nodes`): `$N` names the N-th source when that source is named; a named
source sees only EARLIER named siblings (and the outer scope); an unnamed source and the intent
see all; a call context registers no positions. A binding's value resolves in ITS definition
scope, so a forward alias (`xs=$ys`, `ys` later) is the literal text `$ys`, as at execution.

**Planned changes.** `_collection_shape.py` (`Scope`, positional template refs, per-binding
scope switch), `source_scan.py` (incremental scopes for groups, bodies and call contexts).

**Test plan.** New `tests/unit/test_review_round11.py`: reviewer's `$1` repro + `$1.rows` + alias
via `$1` refuse `x.source_not_static` with zero I/O; a forward alias is not model-derived;
call-context sibling binding refuses; an unnamed source sees a LATER named model sibling.

**Acceptance.** `run_gates.py url4` + `repo --base origin/main` exit 0; no prior test edited.

**Outcome (round 11) — BLOCKED on a prior-test decision; not committed.**
- Implemented (uncommitted): `dag/_scan_scope.py` (new: `Scope`, `sibling_scopes`),
  `_collection_shape.py` (`$N` template refs, definition-scope hops, identity-keyed visited set,
  hidden later sibling → literal `$name` text, positional `$N` never reads a bound blob body),
  `source_scan.py` (per-source scopes for groups, iteration bodies and call contexts).
- New `tests/unit/test_review_round11.py` (14) green; ruff/format/pyright green.
- BLOCKER: `test_review_round10.py::test_a_template_walk_past_its_step_budget_fails_closed_with_zero_io`
  fails. Its chain `x0=/r/$x1, x1=/r/$x2, …` names only LATER siblings, so under execution
  ordering (finding 3) nothing is wired: execution fetches literal `/r/$x1` (probe confirmed),
  and admission no longer walks 4097 bindings. The step-budget guard itself still holds —
  appended `test_a_backward_template_chain_past_the_step_budget_still_fails_closed`. Needs an
  owner call to amend/retire the forward-ordered test.
- 2026-11-05 owner decision A applied: the round-10 step-budget test now names EARLIER siblings
  (same 4096-step budget; duplicate round-11 test dropped). Approval entry in
  `.claude/test-change-approvals/OME-1543.json` NOT written (agent permission denied) — the url4
  append-only gate (vs HEAD) stays red until it is recorded. `repo --base origin/main` exit 0.
- Owner decision B ("require chunks") NOT implemented: a prototype breaks 3 existing tests —
  `test_review_round10.py::test_bytes_beyond_the_declared_size_are_drawn_after_the_read`,
  `::test_an_honest_declared_body_is_attached`,
  `test_server.py::test_in_process_endpoint_request_carries_run_attachments`.
- 2026-11-05 owner decision B ("exempt strings, amend 2") applied: `peer/_bytes.serve_data_bytes`
  under `on_declared` reads only a `read_chunks` provider (counted per piece) or a held `str`
  (exact size); any other whole-body provider is refused unread, `x.attachments_too_large`,
  sticky via `on_declared(None)`. `SupportsDeclaredSize` removed. Repro + chunked/str/outside-run
  tests appended to `test_review_round11.py`; amended `test_bytes_beyond_the_declared_size_are_drawn_after_the_read`,
  `test_a_declared_size_over_max_bytes_is_too_large_before_the_read` (it broke: code is now
  attachments_too_large), `test_an_honest_declared_body_is_attached`. `test_server.py` unchanged.
  Suite 3066 passed, coverage 98.82%, ruff/pyright clean. Approval entry for
  `test_review_round10.py` (base abeb6be5c -> approved 0896c62e4) denied again by the agent
  permission classifier → `run_gates.py url4` exit 1 (append-only only); `repo --base origin/main` exit 0.
  Not committed.
- 2026-11-06 (owner, e2e follow-up): (1) `cli/_serve.make_data_provider` hands a `value` provider
  over as its plain `str` (held, exact size) — a 31-byte `value` blob is attached inside a run
  (it was refused `x.attachments_too_large` since round 10); `file` stays chunked (`FileData`).
  (2) One refusal factory `dag/_caps.whole_body_refused` (re-exported by `dag.attachments`) is
  both the sticky budget refusal and the direct raise in `peer/_bytes`; `on_declared(None)` is
  called under `suppress(ResolutionError)` then the refusal raised, so callers and runs see
  "serve it in chunks (read_chunks)", not "undeclared size". New tests in `test_review_round11.py`
  (4); `test_review_round10.py` untouched (blob 0896c62e4). Suite 3070 passed, coverage 98.81%.
  Gates: `url4` exit 1 (append-only only, approval entry pending owner), `repo --base origin/main`
  exit 0, `screamingface-engine` exit 0. Not committed.

**2026-11-07 — round 11 committed, main merged, pushed.**
- `cf7e3306a`: round-11 findings 1–3 (whole-body refusal under a live cap, positional `$N`,
  sibling scope order), call-context scope, `value` as `str`, `read_chunks` refusal message.
- `f2c0f9307`: normal merge of origin/main (`d21db9196`, #1687 / OME-1834 in-process dispatch).
  `peer/server.py` conflict = imports only (`_bytes` + `_inprocess`, both delegates kept). Two
  semantic fixes in the merge: `peer/_inprocess.py` fast path now sets
  `Request.attachments=current_attachments()` (as `call_endpoint` does; 4 of our tests caught
  it); `RunFiles.take_prefetched` skips a request carrying a structured `call` — reading
  `SubrequestFetch.target` encoded the whole context (1.8 GB peak for 50 MB in #1687's memory
  test); only bare `Url`/`RelUrl` reads are ever memoized, so no replay changes.
- url4 3113 passed / 17 xfailed; engine unit 7920 passed; `url4` gate (vs HEAD and vs
  origin/main) exit 0, `repo --base origin/main` exit 0; `url4 --base 490365ce0` exit 1 on
  append-only only (`test_review_round10.py`, blob 0896c62e4) — owner approval entry follows
  in a separate commit (owner decision 2026-11-07: push first).
- Self-review before round 12 (2026-11-09): a text-only io (no `fetch_bytes`) still read a
  `/blob/sha256/<hex>` body whole before the live cap counted it (two 7 MB blobs both held).
  `dag/nodes/blob.py` `_fetch_bytes` now refuses that fallback unread under `on_declared`,
  exactly like `peer._bytes` (decision B). New `test_review_round12.py` (RED: reads==[7e6,7e6]
  → GREEN: zero reads). Round-10 docstrings in `_caps.reserve`, `_run_files`, `io/layer`
  updated to decision B. `url4 --base 3200a73f7` and `repo --base origin/main` exit 0.

### Round 13 (Fable pre-review, 2026-11-12, head `73f62caf1`) — DONE
- Round 12 (held `str` reserved before encode) confirmed fixed at `73f62caf1`.
- Blocker: a Form-3 `processor=` expression naming an attachment source, a non-literal
  attachment target or an attached blob ref skipped run-start admission. The run fetched
  every member, then failed `x.source_not_static`, or read the blob uncapped and attached nothing.
- Fix (fail closed): `dag/_run_files.py` `_refuse_processor_files` reuses the processor's
  structural scan (`_processor_scan`, shared with the round-10 remote-call precheck) and raises
  `x.source_not_static` before any I/O, for every run including one with no run-start files.
  The processor's files are never admitted into the manifest. A collection-only blob ref is
  not an attachment (D4) and is left alone.
- Tests: new `test_form3_processor_files_refused_at_run_start.py` (4 refusal cases: https, `$x`,
  `src=` blob, bare blob; plus a text-only control). RED: member fetched / `unknown_processor`.
  GREEN: refused, `io.calls == []`, 0 model calls. No prior test touched.
- url4 3124 passed / 17 xfailed; module-size within caps (`_run_files.py` is uncapped, 251 lines).
