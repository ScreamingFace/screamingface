# OME-1191 — Engine implementation plan

1. Add failing parser, lifecycle, REST admission, and scheduling propagation tests.
2. Add a bounded User-Agent parser and Executor decorator in an Engine shared leaf.
3. Carry the optional version through local and queued scheduling. Clear inherited worker
   environment values so absent versions never pick up another run's provenance.
4. Emit one INFO LogData step before inner execution; the existing lifecycle supplies
   Started ordering, sequencing, trace association, replay, and cleanup.
5. Verify no automatic copy into operator logs/OTLP spans; run Engine gates and inspect
   compatibility with the merged Client decoder. Update artifacts and open a draft PR.

User approved implementation and draft PR creation on 11 September 2026. The current
Engine supports local and queued-worker substrates; there is no separate k8s adapter file.

## Approved review refresh — 2026-09-16

Rebase onto current main retaining answer_seed and client_version together; update conflicting test-double signatures without changing assertions. Clarify direct-runner environment responsibility in the spec and move RecordingJobRunner into the existing module-level import. Verify both values survive REST/local and queued/worker handoff, run Engine gates, and push the existing PR. UA comment parsing and shared-helper extraction remain separate follow-ups.
