# Plan

1. Add resolution-level imported-judge activity regression and observe pre-fix behavior.
2. Implement recording scope and explicit judge facts; keep packaging unobserved for imports only.
3. Update Client allowlists and rendering; test compatibility.
4. Switch activity defaults and migrate approved assertions; retain opt-out coverage.
5. Run focused tests and stack gates, inspect diff, prepare review. Do not merge or post Linear comments.

## Expanded diagnosis

Use the existing Engine-authored grading request registry for built-in judge identity,
only inside its owning observation run and outside Candidate execution. Exact request
keys already join judge accounting; ambiguous case ownership remains unattributed.
This avoids changing generated protocols, model inputs, or benchmark identities.

Reserve a terminal-event token when admitting an operation start. The old shared
40-token reserve can be exhausted by parallel rubric calls after their starts escape.
Keep general telemetry admission bounded, preserve explicit suppression counters,
and test burst completion without assuming the downstream bridge is lossless.

User revision: remove pagination entirely; render all retained operations in the existing scroll panel with Copy.
