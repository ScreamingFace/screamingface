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

## Third review pass (2026-08-21)

A review of the complete PR #677 diff found no high-severity correctness bug. Bundle ids match
the directories the old per-family `--out` calls wrote, no caller depended on the old
`tuple[Path, ...]` return, and the family preparers importing `benchmarks.deployment` introduces
no cycle. Three low-severity issues are fixed here; a fourth was examined and deliberately left.

### Fixed

1. **A preparer defect was laundered through the operator-refusal channel.** Pass 2 made a
   non-Mapping return raise `BenchmarkAssetPreparationError` — exactly the class the orchestrator
   CLI catches. So a *programming* defect exited 1 with one line and no traceback, on the same
   channel as answer-key drift, sending an operator hunting for dataset drift that does not exist.
   This contradicted this unit's own `test_builtin_prepare_cli_does_not_hide_unexpected_failures`.
   A new `BenchmarkAssetPreparerContractError(TypeError)` — deliberately outside the
   `BenchmarkAssetPreparationError` hierarchy — keeps the named message while restoring the
   traceback.
2. **A reporting fault could abort the bake.** `json.dumps` runs inside the `on_prepared` callback,
   i.e. inside `prepare_assets`' loop. The port type is `Mapping[str, Any]`, so a future preparer
   putting a `Path`/`set` in its summary would bake draco and leave `ifeval`/`healthbench` unbaked —
   an image shipping missing assets because of a *formatting* problem in the audit record.
   `default=str` keeps a record fault costing fidelity in one line, never the assets.
3. **The family guard derived module paths from bundle ids.** Pass 2's fix read
   `BUILTIN_DEPLOYMENT._asset_bundles` (also private-attribute access). Ids and package names
   coincide today, but this codebase already separates the two (`draco-3pass` is a benchmark id over
   the `draco` bundle). A family declaring `ASSET_BUNDLE_ID = "healthbench-v2"` while its package
   stayed `benchmarks/healthbench` would silently stop being guarded, and a Dockerfile/justfile
   revert to a family call would merge green. The alternation is now derived from the family
   packages on disk (`benchmarks/*/prepare.py`), with a new test asserting the derived set is
   exactly `{draco, healthbench, ifeval}` so a mistyped path cannot yield a guard that matches
   nothing.

### Examined and not fixed

**HealthBench `worst30_cases` is a compile-time constant.** It reports `len(WORST30_CASE_IDS)`, so
it prints 157 regardless of what was baked. Left as is: `emit()` refuses unless today's row order
equals `WORST30_CASE_IDS` exactly, so reaching the summary already proves the frozen subset
verified against today's rows. Changing it would restate the same fact less directly.

### Not filed

The CLI prints no terminal "all bundles complete" record, so a stdout-only reading of a build log
cannot distinguish a finished bake from a truncated one — the reason does reach stderr with a
non-zero exit, which is the channel a build actually fails on. The new repo-root paths use
`Path(__file__).parents[4]` without the `.resolve()` sibling tests use.

### Third pass — outcome

- **Actual files:** `benchmarks/deployment.py`, `benchmarks/prepare.py`,
  `tests/unit/test_benchmark_deployment.py`. No family preparer changed.
- **Gates:** official `run_gates.py screamingface-engine --skip-append-only` — ruff check ✓ ·
  ruff format ✓ · pyright ✓ · check_layering ✓ · pytest --cov (80% floor) ✓ — **ALL GREEN**.
  Focused deployment suite 23 passed. The Dockerfile guard was re-proved by temporarily appending
  a `benchmarks.draco.prepare --out` line and watching
  `test_benchmark_image_invokes_only_the_registered_asset_orchestrator` fail, then reverted.
- **Deviations:** append-only skipped with owner approval, for two lines this pass necessarily
  changes: the guard's derivation source (fix 3 *is* that line) and the contract test's expected
  exception class (fix 1 makes the old assertion assert the defect). Both lines were added by
  **this branch's own pass-2 commit** — `origin/main` has neither the `_asset_bundles`-derived
  guard nor the contract test — so, as in pass 2's deviation 1, this is iterating unmerged work
  rather than rewriting an inherited assertion; the gate flags it because it compares against
  HEAD. Re-running with `--base origin/main` still flags the earlier passes' own changes, already
  covered by their recorded approvals. Nothing was weakened: the replacement test additionally
  asserts the contract error is **not** a `BenchmarkAssetPreparationError` and that the CLI lets
  it through as a traceback.

## Fourth pass — close the PR review findings

### Intent

Close four review findings without widening the unit: make the record's own no-abort promise
true, make the HealthBench summary an observation rather than a restated constant, and stop the
two guards from passing green on the shapes they exist to catch.

### Changes

- `benchmarks/prepare.py` — fence the encoder. `default=` is never consulted for dict KEYS and
  cannot rescue a circular or over-deep summary, so the value-only guard left the documented
  invariant (a reporting fault costs one record, never the remaining bundles) untrue. A failed
  encode now emits `summary_unreportable` with the fault class; the bundle still reports having
  completed.
- `benchmarks/healthbench/prepare.py` — count what landed. `emit` already refuses any row count
  but `PROFESSIONAL_CASE_COUNT`, so echoing its inputs produced a record that could never differ
  between bakes. `professional_cases` and the new `rubric_files` are now read back off the
  written bundle; the serve-time subset size is renamed `declared_worst30_cases` so an operator
  cannot read a compile-time constant as evidence of this run.
- `tests/unit/test_benchmark_deployment.py` — the family guard now also matches a computed
  segment (`$b`, `${family}`, `{name}`); the SDK builds that exact path from a variable today, so
  a literals-only guard passed on the likeliest reintroduction. The three guards that read files
  outside this app now skip when those files are absent, which `packages/screamingface/justfile`
  already anticipates via `SCREAMINGFACE_ENGINE_REPO`.

### Outcome

- **Tests:** two appended — an unserializable summary KEY leaving later bundles intact, and the
  guard matching a computed family segment. Focused deployment suite 25 passed; the broader
  `-k "prepare or benchmark or deployment or healthbench"` selection 249 passed.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ruff check ✓ · ruff format ✓
  · pyright ✓ · check_layering ✓ · pytest --cov (80% floor) ✓ — **ALL GREEN**.
- **Deviations:** append-only skipped with owner approval (asked and granted this pass). The
  edited lines are the guard's own regex and three `REPOSITORY_ROOT` reads — all added by this
  branch's earlier passes, not inherited from `origin/main`. Nothing was weakened: both guards
  now match strictly more, and no assertion was relaxed.
