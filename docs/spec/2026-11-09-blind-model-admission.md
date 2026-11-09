# Spec — refuse a url4 run's attachments for blind models, before any call (OME-1809)

Epic OME-1529 · blocked by OME-1545 (#1588) · related OME-1548, OME-1803, OME-1807, OME-1551 F4.
Branch `blind-model-admission`, cut from `OME-1545-engine-attachment-parts` (1f4cad23f). **The PR
opens only after #1588 merges; this branch then rebases onto main.** That rebase also brings
#1645 (OME-1803: `PDF_MODALITY`, `PART_MODALITIES`, `models_lacking`), which the #1588 branch is
129 commits behind and lacks; this spec is written against main's admission module.

## 1. Problem

Admission runs only on the picture/PDF Benchmark Cases route (`case_selection.py:54,111` →
`picture_admission.refuse_blind_models/refuse_blind_candidate`). A url4 run's own attachments
(frozen at run start by url4, `packages/url4/src/url4/dag/_run_files.py:46` `_run_start`, then
read by every model call through `request.attachments`, `world/connector.py:469,1649`) get no
check. Repro `refusal_text_only_member.url4` (gpt-4o-mini + llama-3.3-70b over an image):
gpt-4o-mini completes and is billed; llama then fails on the upstream 404.

## 2. Facts the design rests on

- The list is fixed before the first node runs and is the same tuple for every model call of the
  run, nested runs included (`url4/dag/attachments.py` RunFiles INVARIANT F2 freeze).
- Attachment targets are literal (`x.source_not_static` refuses model-derived ones), so the
  list's media types are known before any call.
- `ModelSightReader` (`picture_admission.py:63`) gives `model_routes()` (route → gateway id) and
  `input_modalities()` (one `/v1/models` read as the caller; retryable `resolution_failed` when
  unreadable, `connector.py:699`). Registered per gateway node (`connector.py:600`).
- The Runner binds the run's url4 for its length (`run_expression_scope`, `executor.py:1138`).
- Model routes the url4 names: `local_route_paths(url4)` (`expression_routes.py:43`, as executed,
  templates included; remote routes excluded). The node's `default_processor`
  (`connector.py:594`) runs a bare prompt and is a model too.
- A model the gateway does not list counts as text-only (OME-1537).

## 3. Decision

**Where:** in the engine connector, not in url4. url4 stays modality-agnostic (no new run hook).
The first model call of a run that carries attachments performs the run's admission; every other
call of the same run awaits that same result. One check per run, before any chat request leaves
the node.

**What, in order** (new `admit_run_attachments(node, attachments)` in `picture_admission.py`,
called at the top of `call_model` before `_attachment_parts`, `connector.py:469`):

1. No attachments, no bound run url4, or no reader → return (text runs unchanged, byte-identical).
2. Needs = `{modality(a.media_type) for a in attachments}` — `image/*` → `image`,
   `application/pdf` → `pdf` (one table beside `PART_MODALITIES`).
3. Models = `local_route_paths(run_url4) ∩ reader.model_routes()`, plus the node's default
   processor route when the url4 can reach it (Q2). Members, reducers, synthesizers and nested
   Fusions are all routes in the expression, so all are covered.
4. One `input_modalities()` read; blind = `⋃ models_lacking(models, listed, m) for m in needs`.
5. Any blind → `ResolutionError(code=intent_error, permanent=True)` naming every blind gateway id
   and the modality each lacks, in one message. Unreadable list → the reader's retryable error,
   unchanged (fail closed; owner 2026-10-28, PDFs 2026-11-02).

**Once per run:** a run-scoped slot (a `ContextVar` set inside `run_expression_scope`, holding one
`asyncio.Future`/lock) memoizes the outcome — success or the raised error — so parallel members
block on one read and all fail with the same refusal. Graders stay out: a grading call already
refuses files (`connector.py:1655`), and its model is not in the Candidate's routes.

**Benchmark route:** unchanged. A Benchmark run whose Cases carry files is still refused at the
Cases route (C9, #1645); the new check sees the same models and the same answer.

## 4. Non-goals

- No url4 package change, no new error code, no gateway change (#1651 / OME-1807 is the backstop).
- No caching of `/v1/models` across runs (per-caller list).
- Remote-node routes: refused separately when attachments are present (OME-1811).
- Office formats: become text before a run (OME-1550); never a modality here.
- The sync local eval path (no Runner, no bound url4) stays unchecked, as today.

## 5. Owner decisions (2026-11-09)

- **Q1 → (a)** the engine connector: the first model call of a run admits the whole run, and every other call awaits that result. No url4 change.
- **Q2 → (a)** the node's `default_processor` model is checked for a bare prompt.
- **Q3 → (a)** fail closed for every route that can be enumerated; an unseen dynamic route still meets the #1651 gateway backstop.

## 6. Tests (RED first)

`apps/screamingface-engine/tests/unit/test_run_attachment_admission.py`:
- `test_an_image_run_with_a_text_only_member_is_refused_before_any_chat_call` (fake gateway
  counts `/v1/chat/completions`: 0; message names `meta-llama/llama-3.3-70b-instruct`).
- `test_the_refusal_names_every_blind_model_once_sorted`
- `test_a_pdf_run_refuses_a_model_that_lists_image_but_not_pdf`
- `test_a_model_the_gateway_does_not_list_counts_as_blind`
- `test_an_unreadable_model_list_fails_the_run_retryably_before_any_call`
- `test_parallel_members_share_one_model_list_read` (read count == 1)
- `test_a_capable_lineup_runs_unchanged` (requests byte-identical to today's)
- `test_a_text_run_never_reads_the_model_list`
- `test_the_reducer_and_synthesizer_routes_are_checked` (blind reducer refused)
- `test_the_default_processor_is_checked_for_a_bare_prompt`
- `test_a_benchmark_picture_run_is_still_refused_at_the_cases_route` (C9 regression)
Live: re-run `refusal_text_only_member.url4` in the OME-1551 e2e; expect `intent_error`, $0 spend.
