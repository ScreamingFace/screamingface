# OME-1127 — Failure classification investigation

The investigation below records the September 7 baseline. The approved September 9 scope at the end supersedes its proposed policy and branch status.

Status: proposed; live response shape remains unconfirmed.

## Reproduced behavior

Baseline: origin/main a72960dd. Loopback HTTP server, actual AigatewayWorld and URL4 invocation; no provider traffic.

| Response | Code | Retryable |
| --- | --- | --- |
| 200 declares more bytes than delivered, partial JSON | aigateway_transport_error | true |
| 200 declares more bytes than delivered, zero bytes | aigateway_transport_error | true |
| Complete zero-byte 200 | aigateway_bad_response | false |
| Complete HTTP body containing truncated JSON | aigateway_bad_response | false |
| Complete HTML | aigateway_bad_response | false |
| JSON error object with code 503 | aigateway_bad_response | false |
| Choice with null content and finish_reason error | aigateway_bad_response | false |

The last two reproduce the exact issue wording, `malformed aigateway response`. JSON decode failures instead produce the longer non-JSON/proxy message. This distinguishes hypotheses but does not prove the live response shape.

The reproduction asserts interrupted delivery is retryable, HTML is permanent, and an empty 200 is retryable. It fails on the final assertion: `AssertionError: BUG: empty 200 classified permanent`.

## Proposed policy

- Retain existing transport retries and retryable transport classification for actual incomplete HTTP delivery.
- Classify an empty 2xx body as an incomplete-response failure eligible for retry, with wording that does not assert which network hop failed.
- Interpret explicitly recognized provider-error envelopes before attempting to parse a choice. Apply retryability from the error status (429/5xx), not merely the presence of an error object.
- Preserve complete malformed HTML/JSON as gateway faults. JSON truncation alone cannot prove transport interruption when HTTP framing is complete.
- Do not blanket-reclassify null completions: existing refusal, token-cap and malformed-shape invariants remain. Confirm live payload before specifying additional error-completion policy.
- No automatic retry expansion is proposed for completed responses. Retry eligibility and immediate replay of a potentially billable request are separate decisions.
- Keep recorded spend, failed Cases and scores intact. Prefer structural diagnostics (body size, status, finish reason, shape) over raw response excerpts; coordinate broader retention with OME-784.

## COMMIT stage

MedXpertQA is absent from main and exists at origin/OME-1126-medxpert-mcq (inspected 3e9f88e3). Its current definition passes COMMIT as candidate_invocation to preserve_candidate_outcome, while its grading expression also evaluates reasoning. Consequently the reported grading label requires reproduction against the deployed benchmark revision; changing a generic aggregation default would be premature.

## Remaining evidence

Need a sanitized failed response shape or a replay from the reported runtime, plus its Engine/MedXpert revision. The issue explicitly says the failed response was not retained. Synthetic cases demonstrate classification gaps but cannot identify the cause of the two live evaluations.

## Approved implementation scope — 2026-09-09

User authorized proceeding after the scoped problem/solution explanation. Baseline refreshed to origin/main 0dc1b845, including PR #846.

A fully received zero-byte 2xx completion has code `aigateway_empty_response`, permanent=false, with neutral wording that no response body was received and the model request may be retried. No immediate replay is added. Nonempty malformed content, including whitespace-only/HTML/truncated JSON with complete framing, keeps existing bad-response policy. Truly incomplete HTTP delivery keeps existing transport handling.

Regression coverage stays in the Engine landing: a loopback fake Gateway drives the real HTTP connector, Candidate adapter, MedXpert two-turn protocol, and final CandidateResult. Pin both interruption shapes, both candidate turns, genuine checker failures, accounting retained from completed calls, and nonempty malformed/429/503/complete reasoning-only siblings. Broader failure evidence remains OME-784. Existing Engine lifecycle logging addresses runtime visibility; Gateway correlation and duplicate-handler cleanup are follow-ups, not included in this classification unit.
