---
ticket: OME-1970
stack: screamingface-engine
status: done
started: 2026-11-27
finished: 2026-11-27
---

# engine-case-file-refs — the Engine uploads each Case file once per run and sends blob references (OME-1970 PR 7 of 9)

## Intent

A **Case** file (a picture or PDF) rides every model call inline as base64 today, so a 5-member
Fusion on a 13.76 MB PDF sends 6 requests of 18.35 MB each. The gateway now takes a file once per
run (`PUT /v1/blobs/sha256/{digest}`, PR 4) and accepts a **blob reference**,
`blob:sha256/<64 hex>`, where the file would be (PR 5). This unit makes the Engine use them, behind
a flag that defaults off: each Case file is uploaded once per run under a random per-run token,
and every call carries the reference plus that token. If the gateway has no upload route, the
whole run sends inline. On the inline path, run admission refuses a Case too big for the
gateway's 12 MiB body cap before any spend (decision 8).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/case_file_refs.py` (new): the per-run
  state (token, uploads, inline fallback) bound per run, and `reference_parts`.
- `world/gateway_transport.py`: the uploader, and the swap plus the token header on the chat post.
- `world/config.py`, `world/factory.py`, `world/connector.py`, `job_env.py`: the `blob_refs` flag
  (`[aigateway] blob_refs`, env `AIGATEWAY_BLOB_REFS`), threaded to the post.
- `runner/executor.py`: bind the per-run state beside the capture tally.
- `benchmarks/picture_admission.py`, `benchmarks/case_selection.py`: the inline-path admission.
- `deploy/helm/values.yaml`, `values.schema.json`, `templates/configmap-runner-env.yaml`: the
  chart value `config.aigatewayBlobRefs`, default false.

## Test plan

- `tests/unit/test_case_file_refs.py`: a part becomes a reference with the right digest, type and
  size; one upload per file across concurrent calls; a failed upload is retried by the next call;
  no upload route → inline for the run; a declared type the gateway reads differently stays
  inline; two runs get different tokens; the token never appears in a repr; the inline cap
  mirrors the gateway's body cap default.
- `tests/unit/test_connector_case_file_refs.py` (fake gateway): flag off = byte-identical
  request, no upload, no token; flag on = one upload across a Fusion's 5 members and its
  synthesizer, the token on the upload and every call; no upload route → whole run inline;
  inline path refuses an oversize Case at admission before any call.

## Acceptance

- Flag off: today's requests byte for byte (no upload, no token header).
- Flag on: each file uploaded once per run; every call carries references and the run's token.
- No upload route: the whole run inline. Inline path: an oversize Case refused before any call.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Production: `world/case_file_refs.py` (new, 271 lines, most of it
  docstring), `world/gateway_transport.py` (+75), `world/connector.py`, `world/config.py`,
  `world/factory.py`, `job_env.py`, `runner/executor.py`, `benchmarks/picture_admission.py` (+59),
  `benchmarks/case_selection.py`, and the chart (`values.yaml`, `values.schema.json`,
  `templates/configmap-runner-env.yaml`). Tests: `test_case_file_refs.py` (9),
  `test_connector_case_file_refs.py` (10). No prior test changed, so no test-change approval.
- **Commits:** `9a656fb4c` — feat(screamingface-engine): upload each Case file once per run and
  send blob references behind a flag; `1ae9f7665` — feat(screamingface-engine): refuse a Case too
  big for the inline path when its Cases are served.
- **Gates:** relevant tests only (owner rule): the 2 new files plus 28 neighbours that import the
  changed code (connector, transport, retry, frozen copy, picture/PDF admission, Cases routes,
  config, chart contract, job_env contract, layering, executor scope/golden parity): 579 passed.
  ruff check + format clean; pyright 0 errors with and without the `inspect` extra;
  `check_layering.py` OK; `helm template` renders `AIGATEWAY_BLOB_REFS: "false"` by default and
  `"true"` with the value set.
- **Deviations:**
  - The flag reaches the post through a context value set by the connector around its round trip
    (`case_file_refs.sent_by_reference`), not a parameter: a dozen test fakes stub the transport's
    private functions with fixed signatures, and a new parameter would break them.
  - The swap happens in `_post_answered`, once per round trip before its retries, so the frozen
    copy's request digest keeps hashing the inline form (decision 2).
  - Digests are taken per round trip, not once per Case load: each call parses its Case anew
    from text, and a per-run memo keyed by the base64 would hold every Case's bytes for the run.
    Cost: one base64 decode and one SHA-256 per file per call, in a worker thread.
  - `reference_parts` returns `list[dict[str, Any]]`, not `list[CandidateMessage]`: a reference
    part has the `x_` fields no Case shape has, and the call's messages include tool turns.
  - Decision 8 is checked on the raw-rows Cases route only. An Imported Board's route reads no
    row sizes, and every board Case is under the importer's 8,000,000-byte seal cap, which
    `test_picture_case_limits_fit_the_gateway.py` pins under the inline cap. Flag on with no
    upload route falls back inline without the admission check; the gateway's own 413 (before
    any spend) is the backstop there.
  - A part whose declared type differs from what the gateway reads, or whose `data:` URI has
    parameters, stays inline so the swapped-back request equals today's bytes.
