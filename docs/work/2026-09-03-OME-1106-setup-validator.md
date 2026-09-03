---
ticket: OME-1106
stack: repo
started: 2026-09-03
status: in_progress
finished:
---

# OME-1106 — Setup validator for the traceability e2e lanes

## Intent

Running the traceability rungs needs a chain of prerequisites that is only discoverable by
hitting each one in turn. Every item below was found the hard way during `OME-1105`: the
`[runtime]` extra, prepared draco assets, a Docker daemon, `SCREAMINGFACE_TEST_E2E=1`, a
client build carrying `OME-967`, and — for the k8s lane — a kubectl context that currently
does not resolve at all.

The dangerous one is the assets: without them **every rung skips**, and `pytest` exits `0`.
An all-skipped run looks exactly like a passing run to anyone reading the exit code, which is
the single most likely way for someone to believe the chain was validated when nothing ran.

## Design decisions

**D1 — read-only and offline-safe.** The validator probes local state only. It does not SSH,
authenticate, or contact a cluster. Bastion reachability is reported **unknown**, not tested:
probing it is a credentialed action belonging to the operator, and an automated tool that
silently opens sessions to a jump host is the wrong default.

**D2 — `importlib.util.find_spec`, not imports, for the runtime extra.** Importing `litellm`
to check presence is slow and has side effects (it installs logging handlers at import time —
see `OME-1050`). `find_spec` answers the same question without executing the package.

**D3 — exit code reflects the LOCAL lane only.** The local e2e lane is the one that can
actually be made green on a laptop; the k8s lane depends on credentials nobody here controls.
Failing the exit code on the k8s lane would make the validator permanently red and therefore
ignored.

## Planned changes

- `e2e/failor/check_setup.py` — the validator.
- `e2e/failor/notebooks/README.md` — point at it.
- This ledger + the `docs/tasks/` mirror.

## Test plan

No stack gates apply (new file in a top-level directory outside every path filter) — but
**ruff runs repo-wide via pre-commit**, which `OME-1074` established the hard way, so
`ruff check` and `ruff format --check` must be clean. Verification:

- the script runs on this machine and reports a truthful table (verified against the state
  established during `OME-1105`: Docker up, runtime extra installed, draco assets present,
  kubeconfig broken);
- it exits non-zero when a local-lane prerequisite is missing and zero when they are all met;
- it never performs a network or credentialed action.

## Acceptance

- One command reports per-lane readiness with an exact remedy for each missing item.
- It states plainly that a skipped rung proves nothing.
- Clean ruff; no network access.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `e2e/failor/check_setup.py`,
  `e2e/failor/notebooks/README.md` (pointer), the ledger and the mirror.
- **Commits:** `feat(e2e): add a setup validator for the traceability lanes` (sha at
  squash-merge).
- **Gates:** `ruff check` + `ruff format --check` clean (they run repo-wide via pre-commit —
  `OME-1074` established that the hard way). No stack gate applies. **Both exit paths were
  observed**, not reasoned about: `exit=1` with two prerequisites missing, then `exit=0` with
  all five green after `uv sync --extra runtime` in this worktree.
- **Deviations:**
  - **The first version probed the wrong interpreter, and running it caught that.** It used
    the in-process `importlib.util.find_spec`, but the script is invoked as
    `python3 e2e/failor/check_setup.py` from the repo root — so it probed whatever python is
    on PATH, not the client venv, and reported the `[runtime]` extra missing while it was
    installed in the only environment that runs the lane. A validator that lies about
    readiness is worse than no validator. It now probes
    `packages/screamingface/.venv/bin/python` explicitly and labels which interpreter it
    used, falling back with the fallback named in the output.
  - The firecall bastion details (`firecall@172.190.209.255`, AKS `aks-dev-eastus` in
    `rg-aks-platform-dev-eastus`, namespaces `sf-aigw` / `sf-fusion` / `sf-scoreboard`) are
    recorded as constants so nobody has to SSH in to rediscover them. Reachability is
    deliberately NOT probed — see D1.
