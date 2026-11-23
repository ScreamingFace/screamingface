# Recorded Candidate runs

Each file is one run as a follower receives it: `url4` (the run's expression), `trace_id`,
`frames` (the run's CloudEvents, in sequence order) and `record`, the Candidate record of E5 P2
spec §4.3 that those frames give.

`record` is what the Client's fold (`screamingface/_engine/contract.py`, `_RunState`) gave for
the frames when these files were made. The Engine's fold (`screamingface_engine/candidate_record.py`)
is tested against them, so it gives the Client's record for the same run. The Client reads the
Engine's `record` and does not fold the frames itself; its reading of these records is tested in
`packages/screamingface/tests/test_run_record_outcome.py` (the E5 P2 Client PR).

| File | The run |
|---|---|
| `success.json` | One model call, a usage, an inline result. |
| `failure.json` | A provider error ends the run. |
| `cache_hit.json` | Two cache hits, one priced by the provider and one from the archive, and a miss. |
| `capture.json` | A capture run whose seal never came, so it is `partial`. |
| `large_result.json` | A spilled result: the result frame carries an artifact ticket. |
