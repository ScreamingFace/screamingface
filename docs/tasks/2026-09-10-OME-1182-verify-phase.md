---
id: OME-1182
linear_url: https://linear.app/openmined/issue/OME-1182/automate-the-phase-acceptance-check-against-the-deployed-stack
status: done
type: task
priority: 2
labels: [repo, agentic, autonomous, task]
created: 2026-09-10
closed: 2026-09-10
---

# Automate the phase acceptance check against the deployed stack

`OME-1118`'s acceptance was a SigNoz query run by hand. `e2e/failor/verify_phase.py` makes it
repeatable: trigger a run against the deployed engine, read the `trace_id`, poll SigNoz, assert
the phase's signals, exit 0/1/2.

Three properties, each learned from a real defect:

- **Three outcomes, not two.** PASS / FAIL / **BLOCKED**. "No token", "no Access session", "no
  trace id" are failures to *check*, not failures of the phase — reporting them as FAIL sends
  someone hunting a regression that does not exist (`OME-1106` made the opposite mistake twice).
- **Every signal names THIS run.** `Signal.contains` is a tuple whose terms must all appear on
  the SAME line. The first version asserted `gateway_call_id=` alone and passed for a
  fabricated trace id.
- **It triggers its own run.** During `OME-940` a marker's absence was read as "not deployed"
  when the truth was "no run since the merge". Driving the run makes absence real.

Phase signals are DATA (`PHASES`), so Phase 2 adds rows rather than editing control flow.

Ledger: `docs/work/2026-09-10-OME-1182-verify-phase.md`
