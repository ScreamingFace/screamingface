---
id: OME-940
linear_url: https://linear.app/openmined/issue/OME-940/log-engine-run-identity-and-terminal-evidence-on-the-control-plane
status: done
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-10
---

# Log engine run identity and terminal evidence on the control plane

Rung 4a of the correlation ladder, and a Phase 0 child (`OME-935`). A run's frame stream is
deleted 60 s after it ends, so a failed deployed run was not reconstructable after ~2 minutes.
Two lines in the adapters — `run scheduled` and `run terminated` — put identity and outcome
where `kubectl logs` keeps them.

Three things worth knowing before touching this area:

- **The outcome comes from the terminal FRAME, never from the asyncio task.** `lifecycle.run`
  catches a failing run and publishes `Terminated(failed)` instead of re-raising, so the task
  completes normally — reading `task.exception()` reports `succeeded` for every failure.
- **The control plane mints the traceparent when the caller sent none.** Left to
  `lifecycle.run`, the id is decided after the adapter returns, so nothing outside the run ever
  learns it and `job_env.TRACEPARENT` stays unset — which left the runner's whole log context
  with no trace id.
- **The lines log the raw `topic`, contrary to the issue's "digest only".** The topic is the
  *subject* of a capability, not the capability (`auth/jwt.py` signs `{"sub": topic}`; routes
  read it from already-verified claims), and `RunContextFilter` already puts `topic=` on every
  engine log line. Digesting here alone would break grep against the rest of the run's output.
  A repo-wide digest policy would be its own decision.

Ledger: `docs/work/2026-09-10-OME-940-engine-run-evidence.md`
