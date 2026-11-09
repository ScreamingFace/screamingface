# Plan — refuse a url4 run's attachments for blind models, before any call (OME-1809)

Spec: `docs/spec/2026-11-09-blind-model-admission.md` (owner-approved 2026-11-09, Q1–Q3 = a).
Branch `blind-model-admission` (worktree `.claude/worktrees/blind-model-admission`), on top of
#1588. PR opens only after #1588 merges and this branch rebases onto main.
Paths below are under `apps/screamingface-engine/src/screamingface_engine/` unless absolute.
All new tests: `apps/screamingface-engine/tests/unit/test_run_attachment_admission.py`.

## Code facts the plan rests on (checked at 66ea55711)

- `benchmarks/picture_admission.py`: `ModelSightReader` :79, `_READERS` :100, `_RUN_EXPRESSION`
  ContextVar :103, `run_expression_scope` :113 (bound by `runner/executor.py:1138`),
  `candidate_model_routes` :157, `models_lacking` :193, `_REFUSALS`/`_refusal` :219–246,
  `refuse_blind_candidate` :250 (the stage 1–4 shape this reuses).
- `world/connector.py`: `_ModelEndpoint` :409 (`__slots__` :425, `__call__` :448),
  `parts = await _attachment_parts(request)` :493, node built with
  `default_processor="/" + cfg.default_model` :618, `register_model_sight(... _GatewayModelSight)`
  :624, `_GatewayModelSight` :702 (retryable `RESOLUTION_FAILED` when unreadable :734/:739),
  `_attachment_parts` :1770 (grader refusal :1775).
- `benchmarks/expression_routes.py:43` `local_route_paths(url4)`.
- url4 `Attachment.media_type` (`packages/url4/src/url4/dag/attachment.py:33`); `Expression.intent`
  (`packages/url4/src/url4/core/nodes.py:261`).

## Deviations from the spec (code-forced; flagged for review)

1. **The handler has no node.** `_ModelEndpoint` is built before the `Url4Node` (:606 vs :616),
   so `admit_run_attachments(node, …)` cannot look up `_READERS[node]`. Build the
   `_GatewayModelSight` once, before both, hand the same instance to `_ModelEndpoint` (new slot
   `_sight`) and to `register_model_sight`. Signature becomes
   `admit_run_attachments(reader, attachments, *, default_route)`.
2. **Which routes count.** Spec §3.3 says `local_route_paths(run_url4)`, but a Benchmark run's
   url4 also names the protocol and grader routes; a text-only judge would refuse a run whose
   judge never gets files. Plan: when the url4 links a Candidate (`candidate_model_routes` is
   non-empty) use exactly that set; otherwise `local_route_paths(url4) ∩ model_routes()`.
3. **"The url4 can reach the default processor" (Q2)** is made concrete: any `Expression` in
   the walk whose `intent` is a literal `Text` (or absent route) runs on `default_processor`, so
   its route is added. A url4 whose every intent is a route does not add it.

## Tasks (TDD; each RED test fails for the stated reason before its GREEN step)

**T1 — media type → modality table.**
RED: `test_a_pdf_run_refuses_a_model_that_lists_image_but_not_pdf` (no table yet → nothing refused).
GREEN: `picture_admission.py` beside `PART_MODALITIES` :68 add `attachment_modality(media_type)`:
`image/*` → `IMAGE_MODALITY`, `application/pdf` → `PDF_MODALITY`, else `None`.

**T2 — the run check, single call.**
RED: `test_an_image_run_with_a_text_only_member_is_refused_before_any_chat_call` (fake gateway
counts `/v1/chat/completions` == 0; message names `meta-llama/llama-3.3-70b-instruct`);
`test_the_refusal_names_every_blind_model_once_sorted`;
`test_a_model_the_gateway_does_not_list_counts_as_blind`.
GREEN: new `async def admit_run_attachments(reader, attachments, *, default_route)` in
`picture_admission.py` after `refuse_blind_candidate` :250, stages 1–4 of spec §3 reusing
`models_lacking` and `_refusal`; add run-wording entries to `_REFUSALS` (the Benchmark sentences
say "Cases"; a url4 run's must say "this run's attachments"). Raise `ResolutionError(code=
INTENT_ERROR, permanent=True)`. Export in `__all__` :286.

**T3 — wire into the connector.**
GREEN for T2's tests: `connector.py` — build `_GatewayModelSight` before `_ModelEndpoint` (:606),
pass it in (`__slots__` :425 + `__init__` :433 gain `_sight`, `_default_route`), reuse it at
`register_model_sight` :624. In `__call__`, immediately before `_attachment_parts` :493:
`if request.attachments and current_grading_case() is None: await admit_run_attachments(...)`.
(The grader keeps its own refusal at :1775.)

**T4 — once per run.**
RED: `test_parallel_members_share_one_model_list_read` (3 members over one image under
`asyncio.gather`; fake gateway `/v1/models` hit count == 1, all three fail with the SAME error
object text).
GREEN: `run_expression_scope` :113 also sets a second ContextVar `_RUN_ADMISSION` to a fresh
holder `{future: asyncio.Future | None}`; `admit_run_attachments` creates the future on first
entry (synchronously, before any `await`, so no second caller can slip in), runs the check as a
task-independent coroutine, and stores result or exception; later callers `await` it. Outside a
scope (no holder) → stage 1 returns, unchanged behaviour.

**T5 — what is NOT checked.**
RED→GREEN guards: `test_a_text_run_never_reads_the_model_list` (no attachments → 0 `/v1/models`
reads); `test_a_capable_lineup_runs_unchanged` (chat request bodies byte-identical to a
pre-change snapshot captured in the test).

**T6 — route coverage.**
RED: `test_the_reducer_and_synthesizer_routes_are_checked` (blind reducer refused);
`test_the_default_processor_is_checked_for_a_bare_prompt` (`(src=…, 'q')!'d'` with a blind
default model refused).
GREEN: the route set from deviation 2 + the default-route rule from deviation 3 (walk via
`url4.core.parser.build` + `walk`, best-effort like `local_route_paths`: unreadable → no routes,
the run fails on its own stream).

**T7 — unreadable list fails closed.**
RED: `test_an_unreadable_model_list_fails_the_run_retryably_before_any_call` (fake `/v1/models`
→ 503; error `RESOLUTION_FAILED`, `permanent=False`; chat count 0; a sibling member awaiting the
shared future gets the same retryable error, not a pass).
GREEN: nothing new if T4 stores the exception; otherwise fix there. Never cache a failure past
the run (the holder dies with the scope).

**T8 — Benchmark route regression.**
`test_a_benchmark_picture_run_is_still_refused_at_the_cases_route` (C9): existing
`refuse_blind_models` path still answers first; the run check must not double-log or change the
message. Run the existing `tests/unit/test_picture_admission.py` unchanged (append-only gate).

**T9 — docs + gates.**
Ledger outcome; `docs/tasks/` mirror for OME-1809 at PR-open. Gates:
`python3 .claude/scripts/run_gates.py screamingface-engine` and
`python3 .claude/scripts/run_gates.py repo --base origin/main`. Live: re-run
`refusal_text_only_member.url4` in the OME-1551 e2e → `intent_error`, $0 spend.

## Risks

- **Concurrency of the once-per-run admission.** The future must be created before the first
  `await` in `admit_run_attachments`; otherwise two members both see "no future" and read
  `/v1/models` twice (T4 asserts count == 1). Awaiters must not cancel the shared future when one
  member is cancelled: shield it (`asyncio.shield`) so a cancelled member does not fail siblings.
- **Fail closed.** An unreadable list is the reader's retryable error, propagated to every
  member of the run — never treated as "no blind models". A model missing from the list is blind.
- **ContextVar scope.** The holder is set in `run_expression_scope`; url4 member tasks inherit
  the context by copy, so they share the holder object. A run outside the Runner (sync eval)
  has no holder and stays unchecked (spec §4 non-goal).
- **Grader double-refusal.** Admission is skipped for grading calls so the grader's existing
  "judges read text only" refusal stays the one users see.
