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
