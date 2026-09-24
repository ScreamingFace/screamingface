"""Benchmark-independent ensemble protocol substrate (corrective loop).

The corrective runtime itself lives in :mod:`screamingface_engine.world.corrective` (prd/01 F1):
its gate/select/answer endpoints are engine capability, not benchmark surface, and the shared
world package installs them. This package keeps the benchmark-facing vocabulary — the route
names and schemas in :mod:`screamingface_engine.benchmarks.ensemble.policy` — that a Benchmark
definition compiles against.

NOTE: no ``install_corrective_runtime`` re-export here. Re-exporting the world's installer would
make this package import the world while the world imports this package's ``policy`` module,
re-creating the import cycle F1 exists to remove.
"""

__all__: list[str] = []
