---
id: OME-1620
linear_url: https://linear.app/openmined/issue/OME-1620/draco-and-draco-3pass-are-not-installed-by-the-pip-runtime
status: done
type: bug
priority: high
labels: [bug, client-sf, human, deferred]
parent: none
created: 2026-10-15
closed: 2026-11-04
---

# The local Engine serves every Benchmark, not medxpert alone

A pip user's `screamingface up` served medxpert only: the 87 imported Benchmarks live in a
plugin that needs `inspect-ai`, which cannot share an environment with the runtime extra's
litellm pin (OME-1626); the wheel's copied Engine source carried no package metadata, so the
plugin was never found; and `prepare` was a hardcoded list. Three PRs, one ticket, stacked:

- PR 1 (Engine): `serve --local --port N`, so a supervisor that owns the port plan can start the
  local Engine as a child.
- PR 2 (SDK): `up` starts the Engine as a child process from an Engine environment of its own
  (`--engine-python`, `SCREAMINGFACE_ENGINE_PYTHON`, or a checkout's Engine venv found by
  itself); `prepare` runs the Engine's own preparer; a medxpert-only environment is refused at
  `up`; the local Scoreboard seeds from the running Engine over HTTP. Devs are served here.
- PR 3 (SDK): the wheel carries the Engine's plugin, project files and pinned dependency world;
  the first `up` builds the environment under the data dir (uv or pip), keyed by its pins. Pip
  users are served here; closes OME-1626 for Benchmarks (the report exporter still needs its own
  environment).

Owner decisions (2026-11-04): no PyPI publishing of the Engine; three PRs, each useful alone;
the in-process Engine path stays for a checkout without the Engine venv and for a frozen Studio
build (retiring it deletes prior tests, a later owner decision).

Ledgers: `docs/work/2026-11-04-engine-local-serve-port.md` (PR 1),
`docs/work/2026-11-04-sdk-engine-child-process.md` (PR 2),
`docs/work/2026-11-04-sdk-engine-env-builder.md` (PR 3).
