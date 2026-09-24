# OME-1197 — Explicit collected error origin

ResolutionError gains optional origin: a bounded ASCII identifier (lowercase letter followed by up to 63 lowercase letters, digits or underscores). URL4 assigns no domain semantics. Collection includes origin only when explicitly present and valid; old unmarked error JSON remains byte-identical.

The Engine stamps model_call at every connector ResolutionError construction, including conversion of RunnerRequestError. IFEval orphan classification reads this mark instead of error code vocabulary. Protected checker envelopes still classify as grading regardless of the inner origin. Unknown/unmarked origins retain grading fallback. Public error codes/messages/retryability, denominator, successful output, prompts and recipes are unchanged. Other boards may adopt the marker separately.

Owner explicitly approved one cross-package draft under OME-1197, no new ticket, and migrating three legacy tests from hand-built code-only exceptions to actual connector errors. Preserve remaining tests.
