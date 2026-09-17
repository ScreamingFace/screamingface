# OME-1222 implementation plan

1. Write lifecycle and enabled/off integration regressions; demonstrate RED.
2. Add benchmark-owned stage port/wrapper and minimal generic registry access/guard. Extend activity observer with managed sync/async stage scopes.
3. Declare stage wrappers at existing installers, including imported single-shot benchmarks. Keep routes, signatures and handler result contracts intact.
4. Verify explicit coverage and deterministic execution parity; full Engine gates, independent review, documentation outcome.
5. Commit and publish draft PR against main, explaining boundaries and remaining attribution/UI/scoring work.
