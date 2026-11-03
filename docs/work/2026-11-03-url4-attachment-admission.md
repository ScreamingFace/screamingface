---
ticket: OME-1809
stack: screamingface-engine
status: blocked
started: 2026-11-03
finished:
---

# url4-attachment-admission — refuse a url4 run's attachments for models that can't read them

## Intent

Picture/PDF admission (OME-1548, OME-1803) runs only on the picture-Benchmark Cases route. A url4
run's own attachments (#1587 manifest, #1588 content parts) get no check, so a text-only ensemble
member is called and billed and the run then fails on the provider's error (OME-1551 e2e F4,
`refusal_text_only_member.url4`). This unit admits a url4 run's attachments before any model call:
the attachments' modalities (`PART_MODALITIES`) against each called model's published
`/v1/models` `input_modalities`, through the existing `ModelSightReader` port, one read per run.

Owner decisions (2026-11-03): **A + i**.

- **A** — the up-front model set comes from url4's own `compile_expression`, walking the DAG: each
  literal relative fetch adds its path, each `FanoutReduceNode` adds the run's processor route
  (the node's `default_processor`), a literal `processor=` parameter adds its route; lazy
  fragments, map bodies and relative reducers are compiled and walked the same way. Filtered by
  the node's model routes. The url4 node-type dependency sits behind one function.
- **i** — check up front, plus a per-call guard. The run's first model call admits the run once
  (shared by concurrent calls, keyed on the run's `RunFiles`): one permanent `intent_error` naming
  every statically-known blind model and what it lacks. Every later call carrying attachments
  checks its own model against the same single read before it sends (covers computed processors,
  templated routes, iteration bodies). Unreadable list → retryable `resolution_failed`, nothing
  sent. No attachments → no read. Refusals name gateway model ids, never a provider (e2e N3).

## Planned changes

- `benchmarks/picture_admission.py` — `PART_MODALITIES` + `PDF_MODALITY` (identical to #1645, with
  an AIDEV-NOTE to unify on merge); `current_run_expression()`.
- `benchmarks/url4_attachment_admission.py` (new) — part type of a media type, needs, the DAG walk,
  the per-run admission and the per-call guard.
- `world/attachment_parts.py` — `_part` reads the part type from the shared rule.
- `world/connector.py` — `_ModelEndpoint` holds the sight reader and default route and admits
  after the parts are built, before the request is sent. `runner/executor.py` untouched (OME-1811).

## Test plan

- `tests/unit/test_url4_attachment_admission.py` (new, append-only): mixed ensemble with a
  text-only member over an image refused before any chat call, naming the member; a PDF to an
  image-only reducer refused; capable lineups run; unreadable list fails closed with 0 calls; no
  attachments means no list read; a computed processor refused by the per-call guard before its
  send; a templated route; concurrent members share one admission (one list read); the DAG walk's
  shapes (fan-out reduce, `processor=`, lazy fragment, map body, templated path).

## Acceptance

- The ticket's acceptance criteria; Benchmark-route admission unchanged; gates green against
  `origin/OME-1545-engine-attachment-parts`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `world/connector.py` helpers `_default_route` / `_model_ids`.
  `runner/executor.py` untouched. The handler gains NO slots: it builds the `_GatewayModelSight`
  per attachment-carrying call from its existing world-level fields, because
  `test_the_model_handlers_slots_are_exactly_the_world_level_allowlist` pins the slot set (U1-H1).
- **Commits:** 1459c47cd — feat(engine): refuse a url4 run's attachments for models that can't
  read them; 20afd53a9 — merge of the moved `origin/OME-1545-engine-attachment-parts` (27da3e11f).
- **Gates:** ruff, format, pyright, layering green; pytest 6718 passed, 1 failed:
  `test_fair_share_fetch_bytes.py::test_a_gate_bound_run_with_an_https_attachment_reaches_the_model`.
  Its mock gateway answers `/v1/models` with a chat completion, so the new admission reads the
  list as unreadable and fails closed (the owner's 2026-10-28 rule). The fix is a test change —
  the mock lists `MODEL` with `["text", "image"]` — which needs an owner-approved
  `.claude/test-change-approvals/OME-1809.json`. BLOCKED on that approval; not self-approved.
- **Deviations:** probes showed url4 forbids `$` in an expression path (`/m/$x(..)!..` is a
  ParseError) and a templated bare data read of a model route fails (`needs q=`), so a templated
  route cannot reach a model in-process today; the "templated route" test pins that the walk names
  nothing for one, and the per-call guard is proven with a computed (Form-3) run processor. Eval-path
  `processor=` contexts are resolved caller-side (their reduce uses the run's processor); a literal
  `processor=` route is still counted, conservatively. The unreadable-list message is no longer
  picture-only ("pictures or PDFs").
