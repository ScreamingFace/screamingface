# OME-904 — Implementation plan

1. Add Engine tests proving a `Benchmark` may declare a focus line and a dataset link, that both
   reach the `/v1/benchmarks` catalogue entry, that a benchmark declaring neither omits the keys,
   and that declaring them leaves every benchmark's revision unchanged.
2. Give `Benchmark` optional `focus` and `dataset_url` fields with boundary validation, surface
   them in the catalogue metadata, and move DRACO's, IFEval's, and the HealthBench challenge's
   focus lines and dataset links out of the Scoreboard chart into their definitions.
3. Add Scoreboard seed tests covering the catalogue fetch, the mapping onto seed rows, Engine
   precedence over a shadowing configured id, an unreachable Engine leaving a populated board
   untouched, and an unreachable Engine failing when no row carries a revision.
4. Teach `scoreboard.seed` to fetch the catalogue from `SCOREBOARD_SEED_ENGINE_URL`, merge it
   ahead of the configured entries, and raise a seed-owned error for every transport, status,
   and payload failure rather than leaking an HTTP or JSON exception.
5. Replace the chart's hand-typed benchmark prose with `seedBenchmarks.engineUrl`, keep only the
   legacy demo entries, and render the new environment variable on the seed job.
6. Run both stacks' gates, record the outcome in the work ledger, and open the OME-904 pull
   request describing the single-copy invariant.
