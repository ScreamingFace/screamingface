# OME-1161 — Observation seam implementation

1. Record the approved revision and append regression tests for absent/failing observers,
   generic run lifecycle and unchanged operator heartbeat ownership; demonstrate RED.
2. Add core-owned observation protocols and run/call context helpers. Inject a tuple of
   factories into the execution wrapper. Keep execution and cancellation authoritative.
3. Implement the activity adapter and composition registration. Move session ownership,
   model schema translation and loss attributes behind these interfaces.
4. Replace concrete activity calls in executor/connector with generic observations.
   Restore the independent operator heartbeat. Migrate tests coupled to replaced interfaces.
5. Verify plugin deletion in an isolated subprocess, faults, concurrent/cross-task cleanup,
   real fake-provider stream contracts and full Engine gates. Obtain independent review,
   update docs/issue/PR and push the revision without merging.
