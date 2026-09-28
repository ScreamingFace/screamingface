# OME-1197 — Candidate failure boundary

The Engine candidate adapter wraps URL4 errors escaping recipe execution in an Engine-owned CandidateExecutionError (a ResolutionError subclass). Preserve code, message and permanence. Candidate input/policy validation remains outside that execution boundary; refusal results retain their existing handling. Cancellation and unexpected programming exceptions are not caught.

URL4 already serializes exception type in error.kind. No URL4 changes or new wire fields are required. IFEval recognizes CandidateExecutionError for otherwise-unattributed collected failures. Protected checker envelopes still take precedence; unmarked failures retain the existing fallback. Successful outputs, prompts, recipe expressions and scores are unchanged.

This supersedes the draft's origin extension following owner-approved spec/SDK review. The existing SDK probe demonstrated kind preservation through real collection; integration tests must cover the Engine boundary. Source-envelope attribution described by the spec is not yet exposed through this SDK's collected-error payload, so this reuses its existing kind contract rather than adding a protocol feature.
