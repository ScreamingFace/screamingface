# Regrade safety contract

OME-1958, follow-up to Dmitry's #1926 post-merge review. User approved implementation on
2026-11-20. Existing endpoint and ID fixes are #1993.

- Each batch replay is constrained to its transition's target revision. The SDK's optional
  `expected_target_revision` checks the loaded catalogue before executing and the computed
  result before submitting. Sync and async clients behave identically. Batch completion also
  verifies the returned score or an already-existing score belongs to the expected transition.
- A missing source revision summary is an error, even if the current board is empty.
- Journal entry keys include the identity kind (score or spec) and escape delimiter characters.
  Older ambiguous keys are rejected for manual inspection; they are never silently migrated.
- A valid final record without a newline is retained and terminated durably. A complete JSON
  value with invalid fields is rejected unchanged. Only an undecodable unterminated tail is
  truncated after preceding records have been validated.
- A persistent sidecar lock protects the operator's journal pathname; rotating the journal
  cannot permit another process to enter. The active process detects replacement before
  replay/append. Operators must retain the same journal and lock paths on one machine.
- Repeating an identical owner resolution is a no-op, including after a crash partway through
  a group. Conflicting notes and invalid keys reject the entire request before any new append.

No live model calls, production writes or deployments are part of validation.
