---
ticket: OME-1811
stack: python
status: in_progress
started: 2026-11-03
finished:
---

# engine-remote-node-refusal — engine runs refuse url4:// remote-node calls

## Intent

Probe "Gap B" (2026-11-02): `Url4Executor._evaluate` calls `url4.dag.run` directly, outside
`Url4Node.evaluate`, so no remote-node policy is set and a `url4://` remote call reaches the
world node's outbound layer (an empty peer allowlist blocks it with the wrong code
`x.source_destination_blocked`; a populated one lets it reach the peer). Spec #1450 F1b / §4:
every node evaluation, the engine's included, refuses with `x.remote_node_unsupported`
(permanent) before any DNS lookup or request. Parent epic OME-1529.

## Planned changes

- `packages/url4/src/url4/dag/__init__.py`: export `refuse_remote_nodes` (the existing
  awaitable wrapper `Url4Node` already uses) as the supported public hook.
- `packages/url4/src/url4/dag/remote_nodes.py`: AIDEV-NOTE updated; `allow_one_remote_hop` and
  `check_remote_node` stay private.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`: wrap both `url4_run`
  calls in `refuse_remote_nodes(...)`.

## Test plan

- url4 `tests/unit/test_refuse_remote_nodes_public_hook.py`: the hook is in `url4.dag.__all__`;
  under it a remote call, an ensemble member and a `url4://` reduce processor each fail
  `x.remote_node_unsupported` permanent with 0 DNS / 0 requests, empty and populated allowlist;
  control: without it a bare run reaches an allowlisted peer; a local run is unchanged.
- engine `tests/unit/test_engine_remote_node_refusal.py`: `Url4Executor.execute` over a world
  node with the guarded transport, the same three cases x {empty, populated} x {no trace, trace}
  (both call sites); a local run still completes with 0 outbound calls.

## Acceptance

- Engine runs refuse every `url4://` remote-node call with `x.remote_node_unsupported`,
  permanent, 0 DNS lookups, 0 requests; local runs and data fetches unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the two new test files.
- **Commits:** see branch `OME-1811-engine-remote-node-refusal`.
- **Gates:** `run_gates.py screamingface-engine --base origin/OME-1545-engine-attachment-parts`:
  ALL GATES GREEN. `run_gates.py url4` (same base): ruff, format, pyright, pytest (2844 passed,
  98.92% coverage) green; the append-only check fails on one line, see Deviations.
  `check_module_size.py`: all capped modules within baseline (`dag/_context.py` untouched, 455).
- **Deviations:** the url4 H2 ratchet (`tests/unit/test_hygiene_ratchets.py`, `EXPORTS`) pins
  `url4.dag.__all__` at 38; the new export makes it 39. The ratchet says to update it in the same
  diff, but that is a prior-test edit, so it sits in its own commit and needs an owner approval
  manifest (`.claude/test-change-approvals/OME-1811.json`, as OME-1543 did for 59 -> 61) before
  the append-only check passes. The engine test avoids private url4 imports (the engine's
  private-import ratchet): a recording outbound wrapper plus a fail-closed resolver instead of
  mocking `url4.io._guarded_transport`. RED verified: with the executor change reverted, 12/12
  engine refusal cases fail.
- **Moved to main (2026-11-11, owner decision):** the change does not depend on the OME-1543/1545
  stack, so its three commits were cherry-picked onto `origin/main` (efca18049) as branch
  `OME-1811-remote-node-refusal-main`. The ratchet merge took main's base (`url4` 59) plus this
  change (`url4.dag` 39), and the approval manifest was re-pinned to main's blobs (same one-value
  change). Gates on that base: `run_gates.py url4`, `screamingface-engine` and `repo --base
  origin/main` ALL GATES GREEN. The stacked branch `OME-1811-engine-remote-node-refusal` is
  superseded.
