# Score submission metadata limits — OME-969

Reuse the existing `_validate_bounded_metadata` policy for ScoreSubmission:
4096 bytes using the existing ASCII-escaped JSON serialization, maximum depth 4
using the existing baseline depth definition. Rejections identify body.metadata.
Null, omitted, empty, ordinary and exact-boundary metadata remain accepted.
Do not change baseline behavior, add a new dependency or modify stored rows.
