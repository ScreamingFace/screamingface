# Reject termination when the SDK never identified the run root

Refs: OME-1451

When the executed URL4 differs from the compiled URL4, `_RunState` never identifies the
root. It silently accepts termination as a child event and both transports continue
receiving heartbeats indefinitely.

After sequence validation, a valid termination with no identified root must raise
`ExecutionError("SF Engine run root was never identified (URL4 mismatch)")`. This applies
to succeeded, failed, stopped, and timed-out runs. Known child termination and ordered
replay retain their existing behavior. URL4 normalization and gateway retries are outside
this fix.

The existing recorded cache-hit stream provides an offline regression fixture. Replaying
it with its original URL4 must produce an outcome; a mismatched URL4 must raise.
