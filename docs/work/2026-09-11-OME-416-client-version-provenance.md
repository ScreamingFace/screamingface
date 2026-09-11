---
ticket: OME-416
stack: screamingface
status: in_progress
started: 2026-09-11
finished:
---

# OME-416 — Client version provenance, first delivery

## Intent

Identify the Client software making Engine HTTP requests and the source version generating
public notebooks. User authorized starting OME-416 and creating a draft PR after discussing
standard notebook metadata and User-Agent. Engine retention remains separate unresolved scope.

## Planned changes

- Shared private User-Agent helper using the existing installed-version resolver.
- Engine HTTP clients in `client.py` and `_engine/transport.py`, sync and async.
- `scripts/build_notebooks.py` and regenerated `examples/*.ipynb` metadata.
- New regression tests; spec, plan and task mirror.

## Test plan

RED first: request construction proves exact User-Agent and preserved per-request headers for
sync/async catalogue and run transports, including source-tree fallback. Notebook builder tests
prove deterministic namespaced metadata matches its source pyproject, never a different installed
package. Existing output-free/generated notebook checks and complete Client gates remain required.

## Acceptance

Version metadata has no machine/user details; notebook source and output behavior remain unchanged.
Sending the header does not claim Engine storage or returned version provenance. Draft PR only.

## Outcome

- Implemented shared Engine User-Agent on all four HTTP client constructors.
- Added deterministic source-version metadata to the builder and regenerated nine notebooks.
- RED: all 18 new regression cases failed on the original missing header/stamp behavior.
- GREEN: all 18 pass; all prior tests remain unchanged.
- `run_gates.py screamingface`: ALL GATES GREEN (append-only, lint, formatting, pyright,
  full pytest with >=95% coverage, notebook checks, build and distribution checks).
- Parsed-JSON comparison confirms only the new metadata changed in all nine notebooks.
- Wisdom review: shared helper prevents sync/async drift; existing version resolver reused;
  no public API, body schema, auth, retry, visible UI or dependency changes. Source stamping
  avoids silently recording another installed package's version. No telemetry introduced.
- Commit: `feat(screamingface): identify Client requests and generated notebooks` (Refs: OME-416).
- Deviations: none within the stated first-delivery scope. Engine retention/returned provenance
  remain unresolved, and OME-416 stays open. Ticket updates are direct edits, with no comments.
- Logs: `.docs/OME-416-red.log`, `.docs/OME-416-header-red.log`, `.docs/OME-416-gates.log`.
- Draft PR follows validation; not merged.
