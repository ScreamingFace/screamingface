---
ticket: OME-1809
stack: screamingface-engine
status: implemented
started: 2026-11-09
finished: 2026-11-09
---

# blind-model-admission — refuse a url4 run's attachments for models that can't read them, before any call

## Intent

OME-1551 F4: a url4 ensemble over an image calls and bills its capable members, then fails on the
text-only member's provider 404. Admission (OME-1548 / OME-1803) only guards the Benchmark Cases
route. Extend it to every url4 run that carries frozen attachments (#1587 / #1588), so a blind
model is refused by name before any chat call. Spec: `docs/spec/2026-11-09-blind-model-admission.md`.

## Planned changes

- `benchmarks/picture_admission.py` — a run-scoped, once-per-run admission over the frozen list.
- `world/connector.py` — `call_model` awaits that admission before building parts.
- Tests under `apps/screamingface-engine/tests/` (RED list in the spec §6).

## Progress

- 2026-11-09: spec approved (Q1–Q3 = a); plan `docs/plan/2026-11-09-blind-model-admission.md` (9 TDD tasks, 3 code-forced deviations flagged).
- 2026-11-15 (readiness for PR-open after #1588): merged `origin/main` (01e8c8fa0) then
  `origin/OME-1545-engine-attachment-parts` (837ad8dc0). The main merge conflicted only in
  #1587-owned files (`dag/_graph_admission.py`, `dag/_run_files.py`, `dag/remote_nodes.py`,
  `peer/_bytes.py`, `docs/work/2026-10-22-file-refs-carry.md`); resolved to main's version,
  which equals the OME-1545 tip byte for byte. No test changed in the resolution. This branch's
  delta over the OME-1545 tip is still only the OME-1809 files. `OME-1809.json` unchanged: the
  test file's base blob is still e7a07c1f7 on the OME-1545 tip; it validates against that base
  (vs `origin/main` the file is new, so no approval is consulted). Gates vs `origin/main`:
  screamingface-engine green, repo green; url4 red on the append-only check only, for the five
  OME-1545-approved url4 test edits (their approval is bound to the OME-1545 branch). Against
  `origin/OME-1545-engine-attachment-parts` the url4 gate is green. It clears when #1588 merges.
  aigateway gate (as pre-push runs it) green. Not pushed: pre-push runs the url4 gate vs main
  and fails on the check above. Live re-run on a local integration of #1588 + #1750 + this
  branch: `refusal_text_only_member.url4` → terminated `intent_error`, permanent, names
  llama-3.3-70b for images and PDFs; one `GET /v1/models`, 0 chat calls, no cost.usage ($0).
  The sync `GET /` answer is 502 `internal_error`: `rest/routes.py::_sanitized_error` scrubs
  `intent_error` because it is not in `ENGINE_ERROR_CODES` (OME-941 behavior, not this branch).

## Test plan

- See spec §6.

## Acceptance

- Ticket OME-1809 acceptance, verbatim; Benchmark-route admission unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `benchmarks/picture_admission.py`, `world/connector.py`,
  `tests/unit/test_run_attachment_admission.py` (new), `tests/unit/test_fair_share_fetch_bytes.py`
  (owner-approved amendment, `.claude/test-change-approvals/OME-1809.json`), spec, plan, this ledger.
- **Commits:** cf74524d4, 10b1977d5, 7be52a61c, a6173f057, bf97746e0, bf96d9214 (approval), plus
  merges of the OME-1545 stack (incl. #1587's io/layer.py size-ratchet fix 142e90418).
- **Gates:** `run_gates.py screamingface-engine` and `run_gates.py repo --base origin/main` all green
  (2026-11-09). Live (OME-1551 run-2 stack: local aigateway + recording proxy + this branch's engine
  `serve --local`): `refusal_text_only_member.url4` → `intent_error`, permanent, names
  `openrouter/meta-llama/llama-3.3-70b-instruct` for images and PDFs; 0 chat calls at the gateway
  ($0 spend). The proxy saw 2 `GET /v1/models` per run: one is this admission (shared by both
  members), the other the pre-existing `local.py` `_refresh_local_catalog` (local mode only).
- **Deviations:** default processor counts only when a group fans out; reader built per admission
  (handler slots unchanged); the two attachments are still fetched before the refusal (the spec
  guards model calls, not fetches). Nit for review: the joined image+PDF refusal repeats
  "Nothing was sent to a model." once per modality.
- Implementation (2026-11-09): T1–T8 + T10 (OME-1770 masking, from security review) committed
  locally (cf74524d4, 10b1977d5, 7be52a61c, a6173f057); `test_run_attachment_admission.py`
  15 passed. Deviation from plan: the default processor counts only when a group FANS OUT
  (url4 `_wiring._reduce_graph`: every source a relative-expression call, one contributing) —
  a literal-Text intent alone merges locally via `default_process` and calls no model. Handler
  slots unchanged (reader built per admission from world-level fields) to keep
  `test_request_scope_hardening` untouched.
- BLOCKED on owner approval: `tests/unit/test_fair_share_fetch_bytes.py::
  test_a_gate_bound_run_with_an_https_attachment_reaches_the_model` — its mock gateway answers
  `/v1/models` with a chat body, so the fail-closed admission now refuses the run retryably.
  Needs an approved amendment (mock serves `/v1/models` listing `MODEL` with `["text","image"]`).
  Engine gate: 1 failed / 8014 passed.
- PR-open (2026-11-16): merged origin/main after #1588 (OME-1545) squash-merged as 97ec4183c. 10 conflicts,
  all from that squash: 8 files take main's (OME-1545 final) version; `world/connector.py` and
  `test_fair_share_fetch_bytes.py` keep this branch's (main's copy equals the OME-1545 tip, so only
  OME-1809's changes differ). Approval blobs unchanged (base e7a07c1f7 on main, approved b42ae1922).
  Gates green vs origin/main: screamingface-engine, url4, repo.
