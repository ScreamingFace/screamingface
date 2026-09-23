---
ticket: none (owner decision RD4 — commits on sf-refactory, no Linear issue)
stack: screamingface-engine
status: done
started: 2026-09-22
finished: 2026-09-22
---

# sf-refactory — B6 final small fix batch

## Intent

Final small batch of review fix items left after B1–B5 (`04-review-fixes.md`). Eleven
independent items across the runner world-line logging, local-mode mount shape and error
codes, trace scope wording/tests, request scope docs, config guard wording, a hardening test's
module-scan coverage, a fan-out isolation test gap, the layering-check doc sentence and the
Helm README node-tier sizing note.

## Planned changes

- `runner/main.py` (`_model_section` / `resolved()` world-line dedupe for local-on-shared-node).
- `local.py` (direct-mount route set = deployed shape minus benchmarks; shared 400
  `malformed_header` constant; docstring fix on deferred import already covered — here: AIDEV
  note on eval-path reaching benchmarks).
- `tests/unit/test_local_node_mount.py` (update branch-only assertion to new shared code).
- `request_scope.py` (`trace_from_headers` WHY comment; `__post_init__` AIDEV-NOTE on `cache`).
- `trace_scope.py` (docstring wording fix, two spots).
- `world/config.py` (refusal message: exec-mount sentence only for kind `command`).
- `tests/unit/test_request_scope_hardening.py` (scan all loaded `screamingface_engine.*`
  modules, not just `world*`).
- `tests/unit/test_scope_fanout_isolation.py` (new variant: one shared world/handler, two
  concurrent runs, via `build_executor`'s shared-io path).
- `.claude/scripts/check_layering.py` (name the local `/v1?q=` exemption).
- `deploy/helm/README.md` (node-tier sizing note: 512Mi / maxInflight 2 / 64MiB cap).

## Test plan

- Item 1: RED — start a local app, break `url4.toml` after startup, run → must complete (fails
  on HEAD because `resolved()` re-reads the file).
- Item 2: RED — local request to `/benchmarks/candidate` with benchmarks installed must get
  the engine's 404, not a mount hit; a model mount must still work.
- Item 3: existing branch-only test at line 136 pinned the old status/code; update to shared
  `malformed_header` 400.
- Item 4: new test — inbound `...-00` traceparent produces outbound `...-01`, same trace id.
- Item 8: RED — mutant writing the profile into `screamingface_engine.job_env._LAST` must be
  caught once the scan covers all loaded submodules.
- Item 9: RED — mutant that keeps the first caller's scope on a shared handler must be caught
  by the new shared-world variant.

## Acceptance

- `uv run .claude/scripts/run_gates.py screamingface-engine --skip-append-only` green.
- `uv run pytest -q tests/integration` green (37 expected).
- No prior test weakened/deleted; only the two named branch-only tests updated in place.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `.claude/scripts/check_layering.py` (item 10)
  - `apps/screamingface-engine/deploy/helm/README.md` (item 11)
  - `apps/screamingface-engine/src/screamingface_engine/local.py` (items 1, 2, 3)
  - `apps/screamingface-engine/src/screamingface_engine/request_scope.py` (items 4, 6)
  - `apps/screamingface-engine/src/screamingface_engine/runner/main.py` (item 1)
  - `apps/screamingface-engine/src/screamingface_engine/trace_scope.py` (item 5)
  - `apps/screamingface-engine/src/screamingface_engine/world/config.py` (item 7)
  - `apps/screamingface-engine/src/screamingface_engine/world/node_tier/tier.py` (item 3, shares
    `MALFORMED_HEADER`)
  - `apps/screamingface-engine/src/screamingface_engine/world/wire.py` (item 3, new constant)
  - `apps/screamingface-engine/tests/unit/test_local_node_mount.py` (items 2, 3 — item 3 updates
    the branch-only assertion at the old line 136 in place)
  - `apps/screamingface-engine/tests/unit/test_request_scope_hardening.py` (items 4, 8)
  - `apps/screamingface-engine/tests/unit/test_scope_fanout_isolation.py` (item 9)
  - `apps/screamingface-engine/tests/unit/test_world_read_side.py` (item 7)
  - `apps/screamingface-engine/tests/unit/test_world_run_log_namespace.py` (item 1)
  - Item 6 is docs-only (an `# AIDEV-NOTE:`); no test file — confirmed `copy.deepcopy` on a
    `RequestScope` raises `TypeError: cannot pickle 'mappingproxy' object` by hand.
- **Commits:** to be recorded by the caller after this ledger's commit lands.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --skip-append-only` — ALL
  GATES GREEN (ruff check, ruff format --check, pyright, check_layering.py,
  `pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q`).
  `uv run pytest -q tests/integration` — 37 passed.
- **Deviations:**
  - Item 1's fix threads a NEW `io_config_provider` parameter through `build_executor` (rather
    than overloading `io_provider`'s return shape) — kept `io_provider`'s existing contract
    (returns the io layer, nothing else) intact for its other test call sites.
  - Item 2 reuses `rest.forwarder.derive_forward_contract` from `local.py` (building and
    immediately closing a second, benchmark-less world from the same resolved config) rather
    than filtering `node_mount_paths`'s own output, per the spec's "derive it the same way the
    deployed forwarder does".
  - Item 8 required widening `_OPAQUE` to include `type` (class objects) in the test's walker,
    not scanning `screamingface_engine.*` alone — a class in a module's globals (e.g. a Pydantic
    `BaseModel`) raised `PydanticUserError` when its class-level descriptors were read; documented
    inline as an additional stop, not a silent skip.
  - `docs/plans/04-review-fixes.md` and `docs/plans/contracts.md` show as modified in this
    worktree; neither edit is this unit's (docs/plans/ is the orchestrator's) and neither is
    staged or committed here.
