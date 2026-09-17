---
id: OME-740
linear_url: https://linear.app/openmined/issue/OME-740/rework-the-url4-cloud-docker-python-bump-across-both-build-stages
status: in_review
type: task
priority: P2
labels: [url4-cloud, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-740 — move the url4-cloud image's Python across both build stages

Sub-issue of `OME-733` (Dependabot compliance + alert burndown). Replaces #439 — the one PR in
the epic's set that was **broken rather than redundant**, and therefore the only one closed.

## Why #439 could not be merged

`apps/url4-cloud/Dockerfile` is a two-stage build. Dependabot bumped only the runtime stage to
3.14 and left the builder on 3.12, because the two are **different images** —
`ghcr.io/astral-sh/uv:python3.12-bookworm-slim` versus `python:3.12-slim-bookworm` — and it only
recognised the latter as `python`.

The runtime copies the builder's venv wholesale. A venv is version-keyed: `site-packages` lives
under `lib/python<X.Y>/` and `pyvenv.cfg` names the interpreter that built it. Drop a 3.12 venv
into a 3.14 image and the entrypoint resolves to nothing:

```
ModuleNotFoundError: No module named 'url4_cloud'
```

That is an **import-time** fault — the image builds fine. Only CI's `Smoke both modes` step
caught it.

## Target: 3.13, not 3.14

`requires-python = ">=3.12"` permits 3.14, but `url4-cloud-tests.yml` and `url4-tests.yml` run
**3.12 and 3.13 only**. Shipping 3.14 would deploy an interpreter no test in the repo exercises.
Moving to 3.14 must extend the CI matrix in the same change — a separate decision.

## Result

Both `FROM` lines on 3.13. `run_gates.py url4-cloud` all green (append-only, ruff check, ruff
format, pyright, `check_layering.py`, pytest at the 80% floor).

⚠️ No Docker daemon on the authoring machine, so the image was **not** built locally. Image-level
proof rests on CI's `Build the image` + `Smoke both modes`.

## The lasting fix is a comment, not config

Added an `INVARIANT:` and an `AIDEV-NOTE:` to the Dockerfile recording that the two stages must
move together and that **Dependabot structurally cannot do it** — no grouping setting pairs two
different images. `OME-737`'s config rewrite does not solve this one; it is a real limit of the
tool, mitigated by the comment plus CI's smoke step.

Ledger: `docs/work/2026-08-04-OME-740-url4-cloud-docker-python.md`
