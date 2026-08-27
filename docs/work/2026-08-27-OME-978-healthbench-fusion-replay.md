---
ticket: OME-978
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-08-27
finished:
---

# OME-978 — Fusion replay + report-synthesized tape for the healthbench-worst30 board

## Intent

Put the first real ScreamingFace **fusion** leaderboard number (healthbench-worst30,
recipe `best_open_source`, Aug-19 run) under free keyless CI protection. Two parts:
(P1) teach the e2e harness to replay a fusion candidate — golden gains `kind` +
recipe name + lineup, `test_boards` builds the recipe instead of `sf.Model`; (P2) a
`--report` mode in the bless tool that synthesizes the cache tape straight from the
saved SDK report via an iterative capture→splice loop (members → synthesis → judges),
replacing `--dump`/`--answers` — no production dump, no cluster access. Spec lives in
the OME-978 Linear description (rewritten 2026-08-27).

## Planned changes

- `packages/screamingface/tests/e2e/goldens` schema (`GoldenReport` model wherever it
  lives) — add `kind` (`model` | `fusion`), recipe name, member lineup; keep old
  goldens valid (`kind` defaults to `model`).
- `packages/screamingface/tests/e2e/test_boards.py` — build the candidate from the
  golden: `kind: fusion` → construct the recipe with the pinned lineup; single-model
  path unchanged.
- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — `--report` payload
  source (parse SDK report → member/synthesis/judge lookup tables); iterative
  capture→splice loop (one tree level per round, bounded); `--dump`/`--answers`
  become optional/mutually-exclusive with `--report`.
- New unit tests beside the existing bless-contract tests
  (`packages/screamingface/tests/e2e/test_bless_contracts.py` +/- a new module) —
  report parsing, matching, loop-boundedness, golden round-trip — all synthetic, no
  docker, no keys.
- `packages/screamingface/tests/e2e/README.md` — document the `--report` path.

## Test plan

- RED first, per unit:
  - golden with `kind: fusion` + lineup round-trips through `GoldenReport`; goldens
    without `kind` still validate as single-model (backward-compat invariant).
  - `test_boards` candidate-builder: fusion golden → recipe object with exact
    members + synthesizer; model golden → `sf.Model` (unchanged behaviour pinned).
  - report parser: reference-shaped synthetic report → payload tables (3 member
    answers + synthesis per scored case; judge verdicts keyed by (case, criterion));
    failed cases yield NO payloads; `invalid_replies > 0` → loud refusal.
  - capture→splice loop: synthetic 2-level tree converges in ≤ depth rounds; a body
    that matches no payload → loud error naming the case/operation (never a silent
    skip); loop bounded (no-progress round → hard stop).
  - existing draco `--dump`/`--answers` path stays green (test-preservation).
- The paid-run bless itself (P3) is an owner-run command, not CI — out of unit-test
  scope; acceptance covers the machinery.

## Acceptance

- All new unit tests green; every prior e2e/bless test green and unmodified.
- `slice_snapshot.py --board healthbench-worst30 --report <report.json>` runs the
  full loop against the local docker harness (owner executes; command documented).
- Boards without fixtures keep skipping loudly; draco-3pass replay stays green.
- Gates: `uv run .claude/scripts/run_gates.py screamingface` all green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - NEW `packages/screamingface/tests/e2e/fixtures/report_tape.py` — pure seams:
    report → tape parsing, body→payload matching (case-first judge matching,
    failed-case BodySkip), deterministic payload fabrication.
  - NEW `packages/screamingface/tests/e2e/test_report_tape.py` — 24 contract tests
    (default lane).
  - `packages/screamingface/tests/e2e/harness/goldens.py` — GoldenReport gains
    `kind`/`recipe`/`synthesizer` (defaults keep pre-OME-978 goldens valid) +
    `build_candidate`.
  - `packages/screamingface/tests/e2e/test_boards.py` — builds the candidate from
    the golden via `build_candidate` (fusion or model).
  - `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — `--report`
    mode: `_bless_from_report` with the iterative capture→splice loop
    (`_capture_splice_rounds`, bounded at 8 rounds), report-derived
    expect-score/coverage/statuses cross-checks, fusion golden authorship,
    report-provenance snapshot header; `_write_fixtures` refactored to take
    header+golden; `author_golden` extended (old `model=` path byte-identical).
  - `packages/screamingface/Justfile` — `e2e-bless-report` recipe.
  - `packages/screamingface/tests/e2e/README.md` — fusion path in steps ③/④.
  - Planned-but-not-needed: none dropped.
- **Commits:** `f687c031` feat(py-screamingface): bless a fusion board's e2e
  replay from its saved report alone; `34ee0aa4` test(py-screamingface): pin the
  healthbench-worst30 fusion score at -0.091 from blessed fixtures. PR: #755
  (draft).
- **Gates:** `run_gates.py screamingface --skip-append-only` → ALL GATES GREEN
  (ruff check, ruff format, pyright, pytest --cov=screamingface ≥95%, notebook
  check, uv build, distribution check). e2e lane: 76 passed, 16 docker-gated
  skips.
- **Deviations:**
  - Append-only gate overridden with its own `--skip-append-only` flag: the unit's
    approved scope (Linear OME-978) modifies existing test-tree files
    (`test_boards.py` candidate construction, `slice_snapshot.py` extension,
    README). No prior test assertion was changed or weakened — prior test modules
    are untouched; the removed single-model guard in `test_boards` is superseded
    by `build_candidate` + new tests pinning both branches.
  - Worktree venv needed `uv sync --extra notebook` for pyright (ipywidgets) —
    environment, not code.
  - The bless run itself (P3) WAS executed in this unit ($0, keyless, local
    docker): `just e2e-bless-report healthbench-worst30 <owner-held report>`.
    Run 1 failed loudly at the synthesis level — url4 renders a struct `q=` by
    json.dumps-ing the whole object into ONE string (`url4.dag.nodes.StructNode`),
    so member answers reach downstream prompts JSON-escaped and verbatim
    containment could not see them. Fixed test-first (`_contains` now also tries
    both `ensure_ascii` escaped spellings); a full-body dump on unmatched bodies
    was added for diagnosability. Run 2 converged in 4 rounds (372 member + 124
    synthesis + 268 judge rows), verify reproduced the report exactly
    (score −0.091, coverage 0.7898, 124 scored / 33 failed, 19 s), fixtures
    written: snapshot 0.90 MB / 764 rows + manifest + fusion golden.
