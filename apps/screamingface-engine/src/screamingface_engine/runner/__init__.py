"""The DATA PLANE: executing one url4 expression and streaming its observation events.

This is what `screamingface-engine run` enters — the mode the worker pool's children run
(the worker forks each claimed run as a child from its own image). It reads its whole
world from the run's environment (:mod:`screamingface_engine.job_env`) and publishes
to NATS; it serves no port and answers no request.

LAYERING: this subpackage and the control plane (`app`, `rest`, `ws`, `auth`,
`catalog`, `config`, `metrics`, `ops`, `schemas`, `adapters.factory`) MUST NOT import
each other. Both MAY import the shared world package
(:mod:`screamingface_engine.world`, prd/01 F1) and the shared leaves
(:mod:`screamingface_engine.job_env`, :mod:`screamingface_engine.subjects`,
:mod:`screamingface_engine.adapters.jetstream`). `.claude/scripts/check_layering.py`
proves it.

WHY the world is shared (OME-625, prd/01 F1): discovery must answer for the SAME declared world
the run mode executes. A second, partial reader of `url4.toml` on the control-plane side would let
the two disagree — which is the bug that made the Engine advertise a model it could not run — and
the sync surface (unit 3) serves from that same world.

WHY the rule outlived the package split it was born in: the two modes ship in one image and one
venv now, so nothing at runtime stops the run path from importing FastAPI or the kubernetes
client. Keeping the import graph disjoint is what holds a Job's cold start to the engine plus
httpx plus nats-py — the cost the separate slim image used to buy structurally.
"""
