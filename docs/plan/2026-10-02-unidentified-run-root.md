# Unidentified run root implementation

The owner requested implementation and a draft PR for OME-1451 on 2026-10-02.

1. Add a failing regression using the engine's recorded cache-hit stream and a mismatched
   compiled URL4. Add coverage for all termination statuses and replay before root start.
2. Reject termination with `_root_source is None` in `_RunState._terminated` before its
   child-event return. Both transports already propagate this shared decoder's errors.
3. Run the SDK gates, record the results, and create the draft PR. Assign the existing
   issue to the owner and move it to In Review once the PR exists.
