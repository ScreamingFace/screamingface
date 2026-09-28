# OME-416 — Returned Client version provenance

## Intent
Carry the Engine's existing run-scoped screamingface.client.version log attribute into CandidateResult.client_version and portable report JSON. Use the existing ticket, no new Engine contract or ticket.

## Design and planned changes
Decode only sequenced root-source provenance logs. Keep bounded ASCII version tokens (1–128 characters, letters, digits, dot, underscore, plus, hyphen). Ignore malformed values and child/advisory logs; conflicting root versions make provenance unknown. Never substitute the viewer's installed version. Carry the optional value through _RunOutcome and report construction. Public candidate construction validates optional version values. Always serialize client_version, null when absent. No generic report importer currently exists; do not invent one.

## Test plan / acceptance
New tests drive real CloudEvent decoding through report construction and JSON export. Cover absent/invalid/conflicting values, child/advisory logs, replay deduplication, independent runs, direct construction. Preserve prior tests, benchmark identity, scores and prompts. Run full Client gates. Draft PR only, no merge or Linear comments.

## Outcome
Pending implementation and validation.
