# Plan — carry file refs through url4 fan-out, reduce and iteration (`OME-1543`)

Epic `OME-1529`. Ticket `OME-1543` (blocked by `OME-1539`; blocks `OME-1547`). Reviewer: Ionésio
(`dag/semantics`). Governing spec: `docs/spec/2026-10-16-OME-1535-file-input-execution.md` on
#1450 (`OME-1535-file-input-execution-spec`), decisions F1–F3 owner-locked 2026-10-21, plus
**F1b** (owner, 2026-10-21, `3c6ae278e`: plain `https://` sources stay in v1 behind the `OME-1544`
destination guard; F1 still defers `url4://` remote blobs only).
Code read at `origin/main` `ec4b632b2`, plus open PRs #1482 (`OME-1539`, head `703e3105d`), #1478
(`OME-1538`), #1507 (`OME-1678`).

**Status: plan, not approved for implementation.** Implementation starts only on explicit approval.
Open questions Q1–Q5 are resolved by owner decisions D1–D6 (Sergey, 2026-10-21, §6); F1b adds the
`https://` path (§2.7); Q6 and Q7 stay open.

## 0. What this plan changes versus the ticket text

The ticket body predates F2. Where they disagree, F2 wins:

| Ticket says | F2 (locked) says | This plan |
|---|---|---|
| Refs "stay text tokens … recognised and kept intact" through joins | Nothing scans strings; a ref becomes an attachment only from AST structure | No recognition in `_as_text`, `JoinNode`, `build_reducer_input` or `$var`. Refs ride a run-scoped side-channel |
| Reducer input "keeps the original refs alongside member outputs" | Reducer gets `[attachments…, text]`; member outputs add none | Reducer text is unchanged; the reducer call carries the same attachments |
| Recognise `/blob/…`, `url4://…/blob/…`, `blob:sha256/…` | F1 + D1: every `url4://…/blob/…` (any authority, self included) is `remote_blob_unsupported` before any I/O | Only the bare local forms resolve; every `url4://` blob ref fails early |
| (silent on `https://`) | F1b: an `https://` source is fetched through the `OME-1544` guard; a non-text body is hashed into the run store and appended to `attachments[]` | §2.7, U3b; sub-issue A is also blocked by `OME-1544` |

The ticket's two acceptance lines survive unchanged: a ref fanned out to 3 members reaches every
member and the reducer; text-only DAGs are byte-identical.

## 1. Code facts the design rests on (at `ec4b632b2`)

- Every engine model call is a url4 **endpoint call**: members are `RelExpr` fetches; the fan-out
  reducer is `ctx.io.fetch(processor?q=…)` (`U/dag/nodes/group.py:206-262`); `ProcessNode`,
  `MergeNode`, `ReduceNode` go through `ctx.process` or the processor fetch. In the engine all of
  these end in one place: `url4.peer._dispatch.call_endpoint` → `Request(path, context, intent,
  params)` (`U/peer/_dispatch.py:55-64,183-186`) → `_ModelEndpoint.__call__`
  (`E/world/connector.py:411-478`) → `_messages(context, intent)` (`:1478`).
- Payload text is merged by `_as_text` (`U/dag/nodes/_shared.py:47-50`), `JoinNode`
  (`group.py:170-184`), `build_reducer_input` (`U/dag/semantics/ensemble.py:173-188`). #1482's
  `ResolvedBlob(str)` loses its bytes at the first of these joins (`"\n".join` returns plain
  `str`), which is the bug class F2 removes.
- Spawned fragments (map rows, lazy sub-expressions) and guard retries run in tasks created from the
  run's task (`U/dag/executor.py:270-310`), so a `ContextVar` bound by `run()` reaches all of them.
  The engine already carries per-call state this way (`current_scope()`, `current_case_attempt()`,
  `in_candidate_invocation()`).
- HTTP ingress builds `Request` in another task with no run context, so a remote node gets nothing:
  that is F2's remote-node rule for free.
- `model_request_key` hashes `{path, params, context, intent}` (`E/request_identity.py:13-33`) and
  has two callers that must agree: `operation_calls.operation_call_identity` (`:120-150`) and
  `grading_accounting.register_grading_request` (`:60-95`).
- Layering (`U/tests/unit/test_layering.py`): core imports nothing above it; dag may import core;
  peer may import dag. #1482 already defines the value type in `url4.dag.attachment`, so the
  carrier sits beside it in `url4.dag` and `url4.peer` (the `Request` field) imports it from there.
- **#1482 at `703e3105d`** (read with `git show`): `url4.dag.attachment.Attachment` is a frozen
  dataclass `digest` (`sha256:<hex>`), `media_type` (defaults to `OCTET_STREAM` when the adapter
  reports none), `body: bytes` (out of `repr` and equality), `filename`, `detail`. It has no
  `kind`. `BlobRefNode.attachment(ctx)` and `BlobRefNode.resolve` each call `_verified`, which
  fetches through `fetch_bytes` and checks sha256; `resolve` then returns only the ref text. So
  every resolution today fetches and verifies the bytes and throws them away: one fetch per
  evaluation, more under fan-out, map rows and retries (#1482 ledger, deviation 3).
- #1482 marks collection position (D4) at lowering for a **direct** ref only. `$x*(…)` with `x`
  bound to a blob ref iterates the ref text and fails as a scalar collection (#1482 ledger,
  deviation 4, handed to this unit).
- `https://` sources lower to `WebFetchNode` (`U/dag/nodes/fetch.py`), which fetches text; a
  binary body fails `unsupported_content_type` through `io.media.require_text`. The one
  text/binary rule is `io.media.is_text_media_type`.

## 2. Design

1. **Value type: reuse #1482's `url4.dag.attachment.Attachment`.** No second definition anywhere
   (url4 or engine). Its verified `body` rides on it (out of `repr` and equality); consumers
   re-verify `sha256(body)` against `digest` at use (F3). `kind` is not added to the type: the
   engine content builder derives it from `media_type` (`image/*` → `image_url`, else `file`).
2. **Carrier** `url4.dag.attachments`: a private `ContextVar[tuple[Attachment, ...] | None]`,
   public `current_attachments() -> tuple[Attachment, ...]` (empty outside a run). `run()` gains
   `attachments: Sequence[Attachment] = ()` (Case ingress, supplied by the engine) and binds
   `tuple(case_attachments) + url4_refs` **before** the executor starts, resetting it on exit.
3. **Fixed at run start.** Before executing, `run()` walks the parsed AST in source pre-order,
   collects file-ref leaves (`BlobRef`, `/blob/sha256/<hex>` `RelUrl`, `url4://…/blob/…` `Url`),
   skips `RemoteExpr` subtrees (C6) and quoted text (C4), dedupes by digest (first position wins),
   resolves each through `BlobRefNode.attachment` (one `fetch_bytes` under the run's bounded io,
   sha256 verified) into the run cache (item 8), and builds the `Attachment` list. Refs in
   collection position are verified and cached too, but not attached (D4). Any failure fails the
   run before the first model call, including a failed `;optional` blob source (D5: the list is fixed before execution). Every `url4://…/blob/…` ref,
   whatever its authority (the node's own name included), is `x.remote_blob_unsupported`,
   permanent, with zero io calls (F1, D1); only the bare `/blob/sha256/<hex>` path and its
   `blob:sha256/<hex>` token (same node's store) are local. A blob read as a collection (C8) is
   consumed as text and is not attached (D4), including through a binding (item 9).
4. **Nodes cannot add, drop or reorder.** The tuple is immutable; a nested `run()` (local eval
   path, spawned fragment) inherits the bound tuple verbatim; a nested `run()` that would bind a
   *different* tuple raises (`ValueError`, programming error). `BlobRefNode.resolve` returns the ref
   text as a plain `str` and reads the run cache instead of fetching again (item 8).
5. **Endpoint boundary.** `Request` gains `attachments: tuple[Attachment, ...] = ()`;
   `call_endpoint` (in-process) fills it from `current_attachments()`; the HTTP ingress leaves it
   empty. Default-empty keeps every existing `Request(...)` constructor call valid.
6. **Engine side** (separate sub-issue, §5): one builder turns `(text, attachments)` into OpenAI
   `content` (`[image_url|file parts in order…, {"type":"text"}]`, or the plain string when empty),
   taking bytes from `Attachment.body` and re-verifying sha256 on every build. The request key hashes
   the canonical part list and adapter revision only when parts exist, so text-only keys are
   unchanged (D6). Grading calls get `()`: the judge is text-only in v1 (OME-1271, D6). With a
   multi-message candidate envelope the parts go on the **last** user message (D3).
7. **`https://` sources (F1b).** The run-start walk (item 3) also collects every `src=` binding whose
   value is an `http(s)://` `Url` (same exclusions: `RemoteExpr`, quoted text, collection
   position). Each is fetched once through `fetch_bytes`, which goes through the `OME-1544`
   destination guard in the url4 HTTP transport; this unit adds no guard logic and no second
   client. A guard refusal (`x.source_destination_blocked`, `x.source_redirect_limit`,
   `x.source_too_large`, `x.source_timeout`) fails the run before the first model call, as any
   attachment failure does (D5). By `io.media.is_text_media_type`:
   - **text:** cached as text; `WebFetchNode` serves the body from the run cache. No attachment;
     the payload is what it is today.
   - **non-text:** hashed (`sha256`) into the run store as `Attachment(digest, media_type, body)`
     and appended to `attachments[]` at its source position; dedup by digest with blob refs.
     `WebFetchNode` returns the URL text as a plain `str` (as `BlobRefNode` returns its ref text),
     instead of failing `unsupported_content_type`.
   `https://` sources outside a `src=` binding keep today's lazy text fetch (still through the
   guard). Persisting the hashed bytes into the engine's tenant+run store is Q7.
8. **Per-run file cache** (`url4.dag.attachments`, bound with the tuple in `run()`). Keyed by
   digest for blob refs and by URL for `https://` sources; holds the verified `Attachment` (or the
   text body). Filled only by the run-start resolver, so each file is fetched and verified **once
   per run**, whatever the fan-out width, map row count, retries or nested local `run()`.
   `BlobRefNode.resolve` (ref text, or collection text for D4) and `WebFetchNode` read it on a hit
   and keep today's fetch on a miss (a node evaluated outside `run()`, as in #1482's own tests).
   Discarded when `run()` exits.
9. **Blob bindings in collection position (`$x*(…)`) — this unit's scope.** Lowering looks through
   a `$x` binding: when `x`'s value is a file ref and `$x` is read in collection position, that use
   site lowers to its own `BlobRefNode(…, collection=True)` for the same address (structure, no
   string scanning). It reads the cached bytes as text (D4) or fails C8. The ref is attached only
   if some use of it is scalar.

Nothing in `_shared.py`, `group.py`, `broadcast.py`, `reduce.py`, `iteration.py` or
`semantics/ensemble.py` changes: that is the point of F2, and the tests in U4 pin it. Source
changes are limited to `dag/attachments.py` (new), `dag/_run.py`, `dag/nodes/blob.py`,
`dag/nodes/fetch.py` (`WebFetchNode` cache read), `dag/_lowering.py` (item 9), `peer/_dispatch.py`.

## 3. url4 tasks (sub-issue A, `packages/url4`) — TDD order

Prefix `P/` = `packages/url4/`. Every task: write the failing tests, see RED, implement, GREEN,
`run_gates.py url4`. Tests are appended; no existing test is edited.

**U0 — rebase onto the amended #1482.** Precondition: `OME-1539` (#1482) merged **after** it is
amended to D1/D2 (owner decision on Q1): no `ResolvedBlob` `str` subclass (`BlobRefNode` yields a
plain `str`), no `blob_peers` allowlist fetch, every `url4://` blob ref already
`x.remote_blob_unsupported` before I/O. This unit therefore undoes nothing: U0 is the rebase plus a
check that `main` carries those three facts. If #1482 lands without them, STOP and report rather
than reworking it here. `collection_body` (C8) stays as #1482 has it: a blob read as a collection
is text and is **not** an attachment (D4). Second precondition: `OME-1544` (the destination guard
in `io/http.py`, F1b) is merged, so `fetch_bytes` is already guarded and its four `x.source_*`
codes exist; if not, U3b waits and the other units proceed.

**U1 — reuse #1482's `Attachment`.** No new value type: every module imports
`url4.dag.attachment.Attachment`. #1482's `test_blob_refs.py` already pins its fields, the body
out of equality and `repr`, and the octet-stream default, so no test repeats them. New
`P/tests/unit/test_attachments.py`:
1. `test_attachment_is_defined_once` (no other `class Attachment` under `P/src`)

**U2 — the run-scoped carrier and file cache.** New `P/src/url4/dag/attachments.py`; `P/src/url4/dag/_run.py`
(`attachments=` kwarg, bind/reset around `Executor.execute`). Append to
`P/tests/unit/test_attachments.py`:
1. `test_current_attachments_is_empty_outside_a_run`
2. `test_run_without_attachments_binds_empty_tuple`
3. `test_run_binds_case_attachments_in_given_order` (a `process` hook records `current_attachments()`)
4. `test_attachments_are_unbound_after_run_returns_or_raises`
5. `test_concurrent_runs_each_see_their_own_attachments`
6. `test_nested_run_inherits_outer_attachments_unchanged`
7. `test_nested_run_binding_a_different_set_is_refused`
8. `test_run_file_cache_is_discarded_when_run_exits`

**U3 — collect and resolve url4 refs at run start.** `P/src/url4/dag/attachments.py`
(`collect_file_refs(ast)`, `resolve_attachments(addresses, io)`), `P/src/url4/dag/_run.py`,
`P/src/url4/dag/nodes/blob.py` (plain-`str` result read from the run cache), `P/src/url4/dag/_lowering.py`
(item 9), `P/src/url4/core/errors.py`
(only if the amended #1482 lacks `x.remote_blob_unsupported`). Append to `P/tests/unit/test_attachments.py`:
1. `test_collects_refs_in_source_order_across_sources_and_iteration_bodies`
2. `test_collects_both_local_forms` (`/blob/sha256/…`, `blob:sha256/…`; D1)
3. `test_quoted_blob_text_is_not_collected` (C4)
4. `test_refs_inside_a_remote_nested_expression_are_not_collected` (C6)
5. `test_duplicate_digest_is_collected_once_at_its_first_position`
6. `test_case_attachments_precede_url4_refs`
7. `test_remote_blob_ref_fails_remote_blob_unsupported_with_no_io` (io spy: zero calls)
8. `test_url4_blob_ref_naming_the_own_node_is_also_remote_blob_unsupported` (D1)
9. `test_digest_mismatch_fails_blob_digest_mismatch_permanent`
10. `test_missing_blob_fails_source_not_found_before_any_process_call`
11. `test_failed_optional_blob_source_fails_the_whole_run` (D5)
12. `test_blob_in_collection_position_is_text_and_not_attached` (D4)
13. `test_blob_ref_payload_is_the_plain_ref_text_and_fetches_once`
14. `test_each_file_is_fetched_and_verified_once_per_run_across_fanout_rows_and_retries` (io spy:
    one `fetch_bytes` per distinct digest)
15. `test_blob_node_outside_a_run_still_fetches_on_a_cache_miss`
16. `test_bound_blob_in_collection_position_is_text_and_not_attached` (`$x*(…)`, D4, item 9)
17. `test_bound_png_blob_in_collection_position_fails_unsupported_content_type` (C8)
18. `test_bound_blob_used_scalar_and_in_collection_is_attached_once_and_fetched_once`

**U3b — `https://` sources (F1b).** Blocked by `OME-1544`. `P/src/url4/dag/attachments.py`,
`P/src/url4/dag/nodes/fetch.py`. Tests use a fake io whose `fetch_bytes` returns or raises; the
guard itself is tested in `OME-1544`. Append to `P/tests/unit/test_attachments.py`:
1. `test_https_src_returning_an_image_is_hashed_and_attached_at_its_source_position`
2. `test_https_src_returning_text_is_not_attached_and_payload_is_unchanged`
3. `test_https_src_payload_is_the_plain_url_text_when_attached`
4. `test_https_src_and_blob_ref_with_the_same_digest_attach_once`
5. `test_https_src_is_fetched_once_per_run_across_fanout_members` (io spy)
6. `test_guard_refusal_fails_the_run_before_any_process_call` (parametrised over the four
   `x.source_*` codes; `x.source_timeout` stays retryable)
7. `test_https_source_outside_a_src_binding_keeps_the_lazy_text_fetch`
8. `test_https_src_inside_a_remote_nested_expression_is_not_fetched` (C6)

**U4 — inheritance through every node family (the ticket's acceptance).** No source change
expected; these pin it. New `P/tests/unit/test_attachment_propagation.py`, using a `Url4Node` with
recording endpoints and a `StaticIOLayer` blob route:
1. `test_fanout_ref_reaches_all_three_members` (acceptance 1)
2. `test_fanout_reducer_receives_the_same_attachments` (acceptance 1, `FanoutReduceNode`)
3. `test_row_reduce_reducer_receives_the_attachments` (`ReduceNode`)
4. `test_process_node_merge_receives_the_attachments` (`ProcessNode`)
5. `test_broadcast_each_application_receives_the_attachments` (`MergeNode`, incl. `;expand`)
6. `test_map_rows_receive_the_attachments` (spawned rows)
7. `test_pipeline_stage_and_nested_local_expression_receive_the_attachments`
8. `test_guard_retry_resends_identical_attachments` (`;retry`)
9. `test_member_output_containing_blob_text_adds_no_attachment` (no string scanning)
10. `test_reducer_text_is_unchanged_by_attachments` (`build_reducer_input` output equal with and without)
11. `test_text_only_dag_is_byte_identical` (acceptance 2: recorded io targets and result equal a golden from `main`)

**U5 — the endpoint boundary.** `P/src/url4/peer/_dispatch.py` (`Request.attachments`,
`call_endpoint`). Append new functions to `P/tests/unit/test_server.py`:
1. `test_in_process_endpoint_request_carries_run_attachments`
2. `test_http_endpoint_request_carries_no_attachments`
3. `test_remote_fetch_sends_no_attachment_data` (HttpIOLayer request recorded: URL and headers unchanged)
4. `test_request_without_attachments_argument_defaults_empty`

**U6 — public surface and docs.** `P/src/url4/__init__.py` exports `Attachment`,
`current_attachments`; `P/ARCHITECTURE.md` one paragraph (side-channel, fixed at run start, not
shipped to remote nodes). Append `test_attachment_surface_is_exported` to
`P/tests/unit/test_public_api.py` (a new function; the existing tuple is not edited).

## 4. Engine tasks (sub-issue B, `apps/screamingface-engine`) — TDD order

Prefix `E/` = `apps/screamingface-engine/src/screamingface_engine/`, tests under
`apps/screamingface-engine/tests/unit/`. Depends on sub-issue A (the `Request.attachments` field)
and on `OME-1540` for the real store; a Protocol plus an in-memory fake unblocks the tests.

**E1 — scoped blob store port.** New `E/blobs/ports.py`: `RunBlobStore.read(tenant, run_id,
digest) -> bytes` and `put(tenant, run_id, digest, media_type, body)` (refuses bytes that do not
hash to `digest`). Contract: returns verified bytes, `source_not_found` outside tenant+run,
`x.blob_digest_mismatch` on a hash mismatch (store corruption, logged). `read` serves Case-ingress
attachments (the `OME-1678` line); `put` is Q7's write-through for `https://` bytes. New
`test_run_blob_store_contract.py` (run against the fake now, against the `OME-1540` adapter later):
1. `test_reads_bytes_ingested_into_the_same_tenant_and_run`
2. `test_digest_from_another_run_is_source_not_found`
3. `test_digest_from_another_tenant_is_source_not_found`
4. `test_corrupted_bytes_fail_blob_digest_mismatch`
5. `test_put_refuses_bytes_that_do_not_hash_to_the_digest`

**E2 — one content builder.** New `E/world/content_parts.py`: `user_content(text, attachments)
-> str | list[dict]` (bytes from `Attachment.body`, the url4 type imported, never redefined) and `canonical_parts(attachments) -> tuple[CanonicalPart, ...]`,
`CONTENT_PARTS_ADAPTER_REV`. New `test_content_parts_builder.py`:
1. `test_no_attachments_returns_the_plain_string`
2. `test_parts_are_attachments_in_order_then_the_text`
3. `test_image_attachment_becomes_image_url_data_uri_with_detail`
4. `test_other_attachment_becomes_file_data_uri_with_filename`
5. `test_bytes_are_reverified_on_every_build` (a body that no longer hashes to `digest` fails
   `x.blob_digest_mismatch`)
6. `test_canonical_parts_carry_kind_digest_media_type_role_position_detail_filename`

**E3 — connector emits the parts.** `E/world/connector.py`: `_messages(context, intent,
attachments)`; `_ModelEndpoint.__call__` passes `request.attachments` (or `()` for a grading call,
`current_grading_case() is not None`). Append to `test_aigateway_connector.py`:
1. `test_member_call_with_run_attachments_sends_parts_then_text`
2. `test_call_without_attachments_sends_byte_identical_body`
3. `test_reducer_and_synthesizer_calls_in_one_run_receive_the_same_parts` (url4 fan-out + reduce over the fake world)
4. `test_judge_call_inside_a_run_with_attachments_sends_none`
5. `test_envelope_attachments_go_on_the_last_user_message` (D3)

**E4 — request identity (F3).** `E/request_identity.py` gains keyword-only `parts=()` and
`adapter_rev=None`, added to the hashed payload only when `parts` is non-empty;
`E/operation_calls.py` and `E/grading_accounting.py` pass the same parts. New
`test_request_identity.py`:
1. `test_key_without_parts_equals_the_pre_change_golden` (hash literal computed on `main`)
2. `test_key_changes_with_digest`
3. `test_key_changes_with_media_type_position_role_detail_or_filename`
4. `test_key_changes_with_adapter_revision`
5. `test_same_bytes_different_media_type_is_a_different_key`
Append to `test_grading_accounting.py`:
6. `test_operation_identity_and_grading_registration_agree_when_parts_exist`

**Not here:** Case ingress decoding `data:` into the store and `run(attachments=…)` (the
`OME-1678` / `OME-1271` line); the per-type policy (`OME-1548`, `OME-1550`); fusion SDK assertions
(`OME-1547`).

## 5. Proposed sub-issues (not filed)

Cross-cutting (url4 + engine), so one leaf per package under `OME-1543`, epic `OME-1529`:

| # | Title | Landing label | Blocked by | Scope |
|---|---|---|---|---|
| A | Carry run attachments through url4 runs, fan-out, reduce, iteration and retries | `url4-engine` | `OME-1539`, `OME-1544` (U3b only) | U0–U6, U3b |
| B | Send run attachments as content parts and hash them into the model request key | `screamingface-engine` | A, `OME-1540` | E1–E4 |

Overlap: B covers most of `OME-1545` ("Build image and file content parts in the engine
connector"). Recommended: fold B into `OME-1545` (widen it with E4 and the judge rule) rather than
file a new leaf. `OME-1547` (`client-sf`) needs no new leaf: under F2 the fusion text is unchanged
and its synthesizer receives the parts through E3; `OME-1547` shrinks to an SDK-level assertion.

## 6. Decisions (owner-locked, Sergey, 2026-10-21) and what stays open

| Q | Decision | Where it lands |
|---|---|---|
| Q1 #1482 vs F1/F2 | #1482 is **amended before merge** to D1/D2; this unit undoes nothing | U0 |
| Q3 `url4://<self>/blob/…` | **D1** — remote blobs deferred from v1: every `url4://` blob ref, any authority, is `x.remote_blob_unsupported` (permanent) before any network I/O; only the bare local forms resolve | §2.3, U3.2, U3.7–8 |
| — | **D2** — no bytes on `str` subclasses: a typed `Attachment` (digest, media type, optional filename/detail) rides the run's ordered `attachments[]`; `Payload` stays `str`; no string scanning | §2.1–2.5, U4.9 |
| Q4 envelope Cases | **D3** — attachments go on the **last** user message | §2.6, E3.5 |
| Q2 blob in collection position | **D4** — a text blob read as a collection (C8) is text, not attached | §2.3, U0, U3.12 |
| Q5 `;optional` blob source | **D5** — a failed optional blob source fails the whole run (list fixed before execution) | §2.3, U3.11 |
| — | **D6** — judge is text-only in v1; nested expressions on remote nodes get no attachments; no-attachment requests keep today's key | §2.5–2.6, U5.2–3, E3.4, E4.1 |
| — | **F1b** — `https://` sources stay in v1 behind the `OME-1544` guard; a non-text body is hashed into the run store and attached | §2.7, U0, U3b |
| — | **Reuse** #1482's `url4.dag.attachment.Attachment`; no second definition | §2.1, U1, E2 |
| — | **Per-run cache** — a file is fetched and verified once per run (#1482 resolution fetches and verifies but passes only the ref text) | §2.8, U2.8, U3.14–15, U3b.5 |
| — | **Local spelling** is `/blob/sha256/<hex>`; the bare `blob:sha256/<hex>` token also stays local (same node's store). `$x*(…)` over a blob binding is this unit's scope (#1482 deviation 4) | §2.3, §2.9, U3.2, U3.16–18 |

Still open:

- **Q6 — ticket body.** Rewrite `OME-1543`'s description to F2/D1–D6/F1b when the PR opens.
- **Q7 — F1b details for the owner.** (a) Scope: this plan attaches only `https://` values of a
  `src=` binding (the spec's ingress paragraph is about `src=` bindings); every other `https://`
  source stays a lazy text fetch, so text-only DAGs keep their io pattern. Attaching any
  `https://` source would need an eager fetch of every URL at run start. (b) "The run store": url4
  holds the bytes in the per-run cache and on `Attachment.body`; the proposal is an optional
  `run(blob_sink=…)` port that writes them through to the engine's tenant+run store (`E1.put`,
  `OME-1540`) so a replay or audit can read them. Recommended: (a) as planned, (b) write-through.
- **Dependency — `OME-1544`.** The destination guard and its four `x.source_*` codes; U3b waits
  for it.
- **Dependency — `OME-1540`.** The engine's real tenant+run-scoped blob store; sub-issue B tests
  run against a Protocol fake until it lands (§4 E1).
- **Dependency — #1482 amendment (`OME-1539`).** U0 cannot start until #1482 merges amended.

## 7. Gates

- url4: `uv run .claude/scripts/run_gates.py url4`; engine: `uv run .claude/scripts/run_gates.py
  screamingface-engine`; both without `--skip-append-only`.
- Live proof is `OME-1551` (an ensemble over an image and a PDF on the local stack), not this unit.
