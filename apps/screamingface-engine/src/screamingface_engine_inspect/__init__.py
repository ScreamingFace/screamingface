"""The inspect_evals adapter plugin — imported benchmarks as sealed engine-side crates.

This is a TOP-LEVEL package, deliberately not under ``screamingface_engine.``, so an
accidental core import is impossible to write as a relative import and trivially
greppable as an absolute one (spec ``docs/spec/2026-09-09-OME-1113-inspect-evals-import.md``
§3.1). Engine core never imports this package; wiring goes through the
``screamingface_engine.benchmark_deployments`` entry-point group.

The plugin carries every ``inspect-ai`` / ``inspect-evals`` dependency behind the
engine's ``inspect`` uv extra (exact ``==`` pins — §6's revision identity hashes the
pinned versions). Without the extra installed, :mod:`.deployment` contributes nothing
and the engine behaves byte-identically to a plugin-less install.

Judge routing (spec §3.3, zero code): a model-graded inspect scorer resolves its judge
through inspect's own ``openai-api`` provider. Point it at our AI Gateway with the
provider's base-URL + key environment variables in the engine runtime, and every judge
call is metered, rate-limited, and logged under our roof — ``cost_usd`` stays the
gateway meter's number. Neither proof board in this plugin is model-graded; the first
model-graded import (OME-1116) verifies the metered path end to end.
"""
