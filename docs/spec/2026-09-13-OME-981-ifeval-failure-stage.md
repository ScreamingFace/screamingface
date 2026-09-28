# OME-981 — collected IFEval provider failures

Current main c1c92562 and merged PR #913 retain a constant grading fallback. No
other OME-981 implementation PR exists. The older claim that URL4 collection loses
codes is stale: OME-924 retains code and retryable alongside kind/message.

Recognize only the connector-owned diagnostic vocabulary: aigateway_http_400–599,
aigateway_transport_error, aigateway_empty_response, aigateway_bad_response.
These identify failed model calls; IFEval grading is deterministic and its genuine
checker failures are separately protected by the shared case-execution boundary.

Unknown/upstream-defined codes, broad provider_* names, and message-only rows are
not sufficient provenance and keep the existing grading fallback. Retain the
original safe code/message/retryability and Case identity. Malformed evaluation
records still fail validation. No scoring or protocol revision changes.
