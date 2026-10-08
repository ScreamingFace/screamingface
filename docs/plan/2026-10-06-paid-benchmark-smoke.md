# Plan — the paid smoke re-proves every Benchmark

Spec: `docs/spec/2026-10-06-paid-benchmark-smoke.md` · ledger: `docs/work/2026-10-06-paid-benchmark-smoke.md`
· one PR, landing `packages/screamingface` (plus its workflow).

The Paid smoke never runs in this plan: every step is verified with free tests and a
`--collect-only` / dry check. The first real press is the owner's.

## Steps

Each line: step → verify.

1. **RED — the shelf picker's free tests.** New `tests/paid/test_scope.py`, plain `test_`
   functions, no stack, no key:
   - `test_unset_scope_means_every_origin`
   - `test_imported_scope_keeps_only_inspect_evals` / `test_hand_built_scope_keeps_only_screamingface`
   - `test_unknown_scope_fails_naming_the_allowed_values` (because a typo would otherwise pick
     zero Benchmarks)
   - `test_picked_origin_with_no_benchmarks_is_a_problem` (because an Engine booted without
     the inspect extra must not pass on the hand-built ones alone)
   - `test_picked_ids_keep_the_engine_listing_order`
   → verify: they fail on `ModuleNotFoundError: _scope`.

2. **GREEN — `tests/paid/_scope.py`.** The one home of the scope rule:
   ```python
   SCOPE_ENV: Final = "SCREAMINGFACE_PAID_SCOPE"
   ORIGINS_BY_SCOPE: Final[dict[str, frozenset[str]]] = {
       "all": frozenset({"inspect_evals", "screamingface"}),
       "imported": frozenset({"inspect_evals"}),
       "hand-built": frozenset({"screamingface"}),
   }

   class UnknownScopeError(ValueError): ...

   def resolve_scope(raw: str | None) -> str:
       """Check the button's scope word; unset means "all"; anything else raises UnknownScopeError."""

   def pick_shelf(listed: list[tuple[str, str]], scope: str) -> tuple[list[str], list[str]]:
       """Keep the listed (id, origin) pairs the scope covers (`all` keeps every one); also
       name every origin of the scope that listed nothing. Returns (ids in listing order,
       problems)."""
   ```
   → verify: `test_scope.py` green.

3. **Wire the picker into the smoke.** In `test_imported_board_smoke.py` (file name kept:
   the append-only gate cannot approve a rename), rename the test to `test_every_benchmark_runs_end_to_end`; replace the origin filter + the
   empty-shelf assert with `pick_shelf(...)` and a failing assert on its problems (before any
   spend); wording "imported boards" → "Benchmarks" in the progress header and failure
   message.
   → verify: `SCREAMINGFACE_TEST_PAID=1 uv run pytest tests/paid --collect-only -q` lists the
   new name; the free tests in `tests/paid` pass with no key.

4. **Fail a typo before boot.** In `tests/paid/conftest.py`, the `paid_stack` fixture calls
   `resolve_scope(os.environ.get(SCOPE_ENV))` first and turns `UnknownScopeError` into
   `pytest.fail` (always fail, even without REQUIRED — a typo is never "unavailable"). The
   assets guard becomes "at least one prepared bundle" (`*/cases.json`), wording updated.
   → verify: a free test in `test_gating.py`'s style:
   `test_unknown_scope_fails_before_the_stack_boots` (new test, appended).

5. **Rename the fence's expectation.** `tests/test_paid_lane_isolation.py` asserts the
   collected test name; update it to `test_every_benchmark_runs_end_to_end` and the docstring's
   recipe name. `tests/conftest.py` docstring: recipe name. **Prior-test edit — approved with
   this plan**, pinned in `.claude/test-change-approvals/OME-1500.json`.
   → verify: `uv run pytest tests/test_paid_lane_isolation.py` green.

6. **The just recipe.** `test-paid-inspect` → `test-paid-benchmarks scope="all"`; drop the
   `inspect-*` filter from the prepare loop; export `SCREAMINGFACE_PAID_SCOPE={{scope}}`;
   comments say "every Benchmark".
   → verify: `just --justfile packages/screamingface/justfile --dry-run test-paid-benchmarks`
   parses; `just --list` shows it.

7. **The workflow.** `git mv` to `screamingface-paid-benchmark-smoke.yml`; `name:`
   "ScreamingFace Paid Benchmark Smoke"; `workflow_dispatch.inputs.scope` (`type: choice`,
   options `all` / `imported` / `hand-built`, default `all`) passed through `env:` (never
   interpolated into `run:`); `timeout-minutes: 180`; drop the `inspect-*` filter; cache key
   `benchmark-assets-${{ hashFiles(<inspect plugin>/**, <engine benchmarks>/**) }}`; step names
   and header comment say "every Benchmark".
   → verify: `actionlint` on the file (if installed, else a YAML parse + by-eye diff).

8. **Gates.** `uv run .claude/scripts/run_gates.py screamingface` once, before push.
   → verify: green; counts into the ledger Outcome.

9. **Close docs in the PR.** Ledger Outcome filled, `status: done`; `docs/tasks/` mirror
   created at PR-open with `status: done`; the first `scope=all` press goes in the ledger's
   owner-verify note.

## Edge cases checked by design

- `scope` unset (local recipe without the arg, old callers) → `all`.
- Engine lists a third origin someday → `all` keeps EVERY listed Benchmark, whatever its
  origin (the origin set only names which kinds must be non-empty), so nothing is skipped
  silently; `imported` / `hand-built` stay exact filters.
- Scope input injection: the workflow passes `${{ inputs.scope }}` only through `env:`, and the
  choice type restricts it anyway.
