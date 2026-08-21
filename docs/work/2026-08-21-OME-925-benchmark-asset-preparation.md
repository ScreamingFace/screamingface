---
ticket: OME-925
stack: screamingface-engine
status: done
started: 2026-08-21
finished: 2026-08-21
---

# OME-925 — Observable benchmark asset preparation

## Intent

Close the review follow-ups from OME-875 without changing benchmark assets: preserve each
preparer's audit evidence, make expected build refusals readable, and converge local and image
preparation on the deployment entrypoint.

## Planned changes

- Preparation port, deployment result, shared expected exception, and orchestrator CLI.
- DRACO, IFEval, and HealthBench complete-bundle return values and exception inheritance.
- Deployment/CLI/static guard tests, local stack preparation, and accurate benchmark-image CI
  naming.
- Task, spec, plan, work ledger, and draft-PR evidence.

## Test plan

- RED: summaries survive shared-bundle deduplication in stable order.
- RED: CLI prints one structured record per bundle and handles declared failures without traceback.
- RED: Docker and local preparation reject any family-specific entrypoint and derive the root.
- RED: CI names the complete benchmark image accurately.
- GREEN: focused deployment tests, then the complete `screamingface-engine` gate suite.

## Acceptance

- Build logs expose DRACO cases, IFEval cases/patched keys, and the HealthBench board split.
- Expected preparer refusals are concise and non-zero; unexpected exceptions remain visible.
- Image and local preparation use one registry-derived command.
- CI describes the complete benchmark image accurately without changing its proven build path.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the preparation port/deployment/orchestrator; all three family adapters;
  deployment, process-boundary, Docker, justfile and workflow contract tests; the local justfile;
  the CI step name; and this unit's task/spec/plan/work records.
- **Commits:** the `fix(screamingface-engine): make benchmark asset preparation auditable`
  commit carrying this outcome (`Refs: OME-925`).
- **Gates:** official `run_gates.py screamingface-engine --skip-append-only` — ALL GATES
  GREEN (Ruff check/format, Pyright, layering, full pytest with coverage); 1,938 tests
  collected; focused deployment/preparer suite 42 passed; workflow YAML and justfile parsed.
- **Deviations:** append-only was skipped with owner approval because the ticket explicitly
  changes the inherited preparer return contract and strengthens its Dockerfile assertion.
  No inherited behavior or assertion was weakened. Persistent dataset/corpus caching was deferred:
  the proposed registry/layer-cache plumbing did not guarantee preservation of BuildKit cache
  mounts across fresh runners and was removed before review.

## Second review pass (2026-08-21) — planned

A follow-up review found five issues. Four are fixed here; the fifth is a claim correction plus a
follow-up ticket, because the actual repair crosses stacks.

### Fixed in this pass

1. **The justfile guard could never fire on the file it guards.**
   `test_local_stack_prepare_uses_the_registered_asset_orchestrator` reads
   `packages/screamingface/justfile`, but `screamingface-engine-tests.yml` triggers only on
   `apps/screamingface-engine/**`, `packages/url4/**` and itself — and `screamingface-tests.yml`,
   which does cover that path, runs no engine tests. A PR reverting `stack-prepare` to three family
   calls would merge green and the guard would later fire on an unrelated engine PR, blaming the
   wrong change. `packages/screamingface/justfile` is added to the engine workflow's `paths`.
2. **A refusal discarded the evidence for bundles that already baked.** Records printed only after
   every bundle finished, so a HealthBench failure lost draco's completed summary — the exact
   auditability this unit adds. `prepare_assets` now reports each bundle as it completes, and the
   CLI streams the record then.
3. **The guard regex was broader than its message.** `benchmarks\.[a-z0-9_]+\.prepare` under
   `search()` matched any middle module and `.prepare` as a prefix, so a reference to
   `benchmarks.deployment.prepare_assets` would fail as a "family-specific invocation". The family
   segment is now derived from the deployment's own bundle ids and anchored.
4. **The copy invariant overstated itself.** `dict(...)` is shallow, so the promise held only for
   top-level keys; and a preparer still written against the old `-> None` contract produced a bare
   `TypeError`. The comment is corrected and a non-Mapping return now raises a named contract error.

### Not fixed here — claim corrected, ticket filed

**`screamingface prepare` still calls the family preparers directly.**
`packages/screamingface/src/screamingface/_runtime/cli.py` shells
`benchmarks.{name}.prepare --out` per family from a hardcoded `_BENCHMARKS`, so the audit envelope
never reaches the command a user actually runs. The PR body's "the only complete preparation path"
is corrected. The repair is NOT a tidy: it is a different stack (rule 8 → epic + per-package
sub-issue), `prepare_assets` has no single-bundle filter so `screamingface prepare draco` has no
equivalent, and the SDK owns its own manifest, fingerprint, validation and `--force` logic. Filed
separately rather than smuggled in.

### Test plan

- RED: a two-bundle deployment whose second bundle refuses still reports the first bundle's summary;
  the CLI prints that record before the failure line.
- RED: the family-preparer guard does not match `benchmarks.deployment.prepare_assets`.
- RED: a preparer returning `None` raises a named contract error, not a bare `TypeError`.
- The engine workflow's `paths` include `packages/screamingface/justfile`.
- Prior tests unchanged except where the streaming contract requires it.

### Second review pass — outcome

- **Actual files:** `.github/workflows/screamingface-engine-tests.yml`, `benchmarks/deployment.py`,
  `benchmarks/prepare.py`, `tests/unit/test_benchmark_deployment.py`. No family preparer changed.
- **Gates:** ruff check ✓ · ruff format ✓ · pyright ✓ · check_layering ✓ · pytest --cov (80% floor)
  ✓ — **ALL GREEN**. Focused deployment suite 20 passed. Workflow YAML re-parsed and both `paths`
  lists verified.
- **`prepare_assets` grew an optional `on_prepared` callback** rather than printing from the
  orchestrator, keeping the I/O decision with the CLI. The CLI streams each record with `flush=True`
  so a build log keeps the completed bundles when a later one refuses.

### Deviations from the plan

1. **Three tests in this same branch needed their monkeypatch signature updated.** They stub
   `prepare_builtin_assets`, which gained the callback parameter. These are tests this PR itself
   added — not inherited from `main` — so this is iterating unmerged work, not a rule 5 exception.
   No inherited assertion was touched by this pass.
2. **My first guard probe was wrong and passed for the wrong reason.** It asserted on
   `benchmarks.deployment.prepare_assets` without the `screamingface_engine.` prefix, so the regex
   never had a chance to match. Corrected to the fully-qualified string, which then failed RED as
   intended before the fix.
3. **`BenchmarkDeployment` is slotted**, so the new test could not monkeypatch `prepare_assets` on
   the built-in instance; it substitutes `prepare_builtin_assets` instead, matching the style of the
   sibling CLI tests.
4. **Two line-length violations** were caught by ruff, not by the test run.

### Follow-up filed separately

`screamingface prepare` still calls the family preparers directly, so the audit envelope never
reaches the command a user runs. Live corroboration on the owner's machine: all three asset
directories hold real content and the Engine served evaluations from them, yet
`screamingface prepare --list` reports every one `incomplete`, because the orchestrator path writes
none of the SDK's manifests. Two paths, two notions of "prepared", disagreeing. Not repaired here:
different stack (rule 8 → epic + per-package sub-issue), `prepare_assets` has no single-bundle
filter so `screamingface prepare draco` has no equivalent, and the SDK owns its own manifest,
fingerprint, validation and `--force` semantics.
