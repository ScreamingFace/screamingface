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

Judge routing (OME-1240 — this CORRECTS spec §3.3's env-var plan, which could never
meter): a model-graded inspect scorer names its judge ``screamingface/<gateway-model-id>``
and resolves it through :mod:`.judge_provider` — an inspect model provider whose only
exit is the node's own declared model route. The aggregate binds the transport per
grading pass, so judge calls ride the same connector as every candidate call: routed,
identity-stamped, and reported into the run's usage sink (``cost_usd`` counts judge
tokens). The judge's model, params, and prompt join the board's revision (its
``JudgeSpec`` row declaration). inspect's ``openai-api``-plus-env-vars route is
forbidden here: it would bypass the usage sink and silently drop judge cost from the
report. FrontierScience is the proof board.
"""
