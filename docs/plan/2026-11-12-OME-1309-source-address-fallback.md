# Improve draft source checking locally

1. Add failing regression tests for an unreachable first DNS address and a reachable alternative.
2. Implement bounded fallback using already validated addresses and preserve request identity.
3. Verify all-failure, security refusals, HTTP/read-error behavior and overall deadline; run scoreboard gates.
4. Leave the result local for user review, with no GitHub or Linear writes.
