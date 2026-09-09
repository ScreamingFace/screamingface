---
ticket: OME-1099
stack: screamingface-engine
status: in_progress
started: 2026-09-09
finished:
---

# OME-1099 — Merge the three drifted judge-verdict parsers into one typed shared parser

## Intent

Verdict parsing (judge reply → typed record with mandatory audit fields) exists four
times: `rubric_check.py`'s verdict section and the three per-board `verdict.py` files
(draco, healthbench, gdpval). The copies have drifted (0.45 similarity between the two
that share a docstring), and the drift already cost us OME-1023 (a copy silently
dropped `raw_output` on valid verdicts). This unit merges the *parsing* into one spine
module with a typed record whose audit fields are required constructor arguments, so a
new rubric board cannot drop an audit field. Per-board verdict *semantics* stay
board-owned via shape declarations. Delivers OME-1025.

## Planned changes

- **Create** `src/screamingface_engine/benchmarks/spine/verdict.py` — the one parser:
  - `Verdict` frozen dataclass: `schema`, `identity` (engine-stamped ids), `producer_id`,
    `raw_output`, `valid`, `payload`, `reason` — **no defaults on audit fields**, so
    omitting `raw_output` fails both pyright and runtime construction. `.record()`
    projects to the wire dict the runtimes persist today (byte-identical keys/values).
  - `VerdictShape` frozen dataclass — per-board declaration: `schema`, status field
    name + accepted values (enum `("MET","UNMET")` vs strict JSON bool), whether
    `explanation` is required, and the board's reason-string vocabulary (canonical
    failure code → board wire string), so each board's `reason` values stay
    byte-identical.
  - Shared JSON recovery: fence stripping + first-JSON-value fallback (today
    byte-identical in all three `verdict.py`), exposed for both `{`-objects and
    `[`-arrays.
  - Shared `rubric_binding_key` (healthbench/gdpval byte-identical today) and shared
    rubric `call()` retry wrapper (healthbench/gdpval byte-identical today).
- **Reduce** `benchmarks/draco/verdict.py`, `benchmarks/healthbench/verdict.py`,
  `benchmarks/gdpval/verdict.py` to shape declarations + board-specific wiring
  (draco keeps its own `call`/`binding_key` — different intent format); public API
  (`SCHEMA`, `bind`, `binding_key`, `call`) unchanged so runtimes/exams/case_results
  keep importing from the board modules.
- **Rewire** `benchmarks/rubric_check.py` `_decoded_array` onto the shared JSON
  recovery (the check surface's ordinal-array parsing stays local — different shape,
  same recovery primitive).
- **Export** the new names from `benchmarks/spine/__init__.py`.
- Spine collision note honored: no edits to `benchmarks/contract.py` or
  `benchmarks/aggregation.py`.

## Test plan

- New `tests/unit/test_spine_verdict.py` written FIRST:
  - typed-record invariant: constructing `Verdict` without `raw_output` raises
    `TypeError` at runtime and fails pyright (`# type: ignore` + pyright's
    reportUnnecessaryTypeIgnoreComment behavior verified; runtime TypeError is the
    floor);
  - one parse produces the exact wire dicts each board produces today (golden dicts
    lifted from the current implementations for all three shapes: valid, fenced,
    prose-prefixed, empty, non-JSON, wrong-shape, wrong-status/non-bool);
  - reason strings per board byte-identical to today's.
- All existing tests stay green and unmodified: `test_draco_verdict.py`,
  `test_gdpval_verdict.py`, `test_healthbench_runtime.py`, check-surface tests —
  they now exercise the shared parser through the board modules.

## Acceptance

- One parser module; the three `verdict.py` files reduced to shape declarations.
- Type-level test: a verdict record without the raw reply does not typecheck.
- Full engine gate green (`run_gates.py screamingface-engine`); prior tests untouched.
- Diff under ~700 lines.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — new `benchmarks/spine/verdict.py` (341 lines) +
  `tests/unit/test_spine_verdict.py` (34 tests); `draco/verdict.py` 179→110,
  `healthbench/verdict.py` 194→57, `gdpval/verdict.py` 195→56 (shape declarations +
  board-owned wiring); `rubric_check.py` `_decoded_array` → shared `recovered_array`;
  spine `__init__` exports. `contract.py`/`aggregation.py` untouched (collision note).
- **Commits:** this branch's single squash-bound commit —
  `refactor(screamingface-engine): merge the drifted judge-verdict parsers into one
  typed spine parser` (`Refs: OME-1099`).
- **Gates:** ruff check ✓ · ruff format ✓ · pyright 0 errors ✓ · check_layering ✓ ·
  pytest 2680 passed, 8 skipped, coverage 93.08% (≥80) — 1 pre-existing failure
  unrelated to this unit: `test_worker_child_memory_cap` (OME-1089, merged 2026-09-08)
  fails on macOS because Darwin refuses the exec wrapper's `RLIMIT_AS` lowering
  ("current limit exceeds maximum limit"); fails identically on unmodified `main`,
  passes in Linux CI. Surfaced for its own ticket, not touched here.
- **Deviations:** four micro-behaviors on degenerate inputs, all wire-invisible on real
  runs and unpinned by any prior test:
  1. gdpval `bind` no longer strips whitespace from `producer_id` (draco/healthbench
     majority behavior; runtimes pass clean ids).
  2. gdpval valid-verdict `explanation`: non-string values now become `""` (healthbench
     behavior) instead of `str()` coercion (which turned `None` into `"None"`).
  3. check-surface fence stripping now tolerates indented ``` fences (the shared
     primitive strips `line.strip().startswith`; old array copy used `line.startswith`).
  4. producer-id ValueError message unified to "producer_id must be non-empty text"
     (gdpval said "a non-empty string"; tests pin the raise, not the message).
