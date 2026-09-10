---
ticket: OME-1098
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-09-09
finished: 2026-09-10
---

# OME-1098 — Harness prep for the ifeval (corrective-loop) and gdpval-text goldens

## Intent

The dev half of OME-1098 (scope widened, owner-approved 2026-09-09): make the e2e
bless/replay harness able to consume the owner's upcoming recordings — a CorrectiveLoop
run on ifeval (limit=50) and a Fusion run on gdpval-text (limit=25) — so both boards can
be blessed the moment the paid recordings exist. Three pieces:

1. **Fresh-dump bless mode** in `slice_snapshot.py`: a fresh recording through the
   current gateway already carries correct cache keys, so this mode skips the capture
   and re-key stages entirely (load dump → keyless verified replay → slice → golden).
   Candidate-shape-agnostic — it never inspects request bodies — which is what makes a
   loop golden possible (report mode refuses non-fusion; the legacy dump path assumes
   one request per case).
2. **`kind: "corrective_loop"` golden**: `GoldenReport` gains the third candidate kind
   (members + judge + max_rounds) and `build_candidate` reconstructs
   `sf.CorrectiveLoop(...)`.
3. **gdpval-text board registration**: `BOARDS` + `_ASSET_BUNDLE` in `test_boards.py`
   and `_ASSET_BUNDLE` in `slice_snapshot.py`.

Blessing itself (step 3 of the ticket) waits on the owner recordings and is NOT this
unit.

## Planned changes

- `packages/screamingface/tests/e2e/harness/goldens.py` — `kind: "corrective_loop"` +
  `judge`/`max_rounds` fields (defaults keep every committed golden valid) +
  `build_candidate` branch.
- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — new `--dump-fresh`
  exclusive mode (dump + expected outcomes in, no `--answers`, no re-key); gdpval-text
  in `_ASSET_BUNDLE`.
- `packages/screamingface/tests/e2e/test_boards.py` — `gdpval-text` in `BOARDS` +
  `_ASSET_BUNDLE`.
- New/extended unit tests beside the existing bless-contract tests (no docker, no keys).

## Test plan

RED first, per unit:

- Golden with `kind: "corrective_loop"` + members/judge/max_rounds round-trips through
  `GoldenReport`; goldens without `kind` still validate as single-model and fusion
  goldens stay valid (backward-compat invariant — append-only schema).
- `build_candidate`: corrective_loop golden → `sf.CorrectiveLoop` with exact members,
  judge, max_rounds; model/fusion behaviour pinned unchanged.
- `--dump-fresh` argument contract: mutually exclusive with `--model/--answers/--report`;
  missing dump refuses loudly; gdpval-text resolves an asset bundle.
- Fresh-dump slicing seams: pure functions unit-tested (dump parsing reuses the existing
  COPY-line seams — no new escaping authority).
- Existing `--dump/--answers` and `--report` paths stay green and unmodified
  (test-preservation).

## Acceptance

- All new unit tests green; every prior e2e/bless test green and unmodified.
- `gdpval-text` and `ifeval` both skip loudly in the e2e lane ("no recorded fixtures
  yet") until their fixtures land.
- Gates: `uv run .claude/scripts/run_gates.py screamingface` all green.
- The documented owner command for each board is in `tests/e2e/README.md`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - NEW `packages/screamingface/tests/e2e/test_fresh_dump_contracts.py` — 14 contract
    tests (default lane): corrective_loop golden round-trip + refusals,
    `build_candidate` loop branch, `author_golden` loop shape, `parse_candidate_spec`
    + `parse_fresh_report` seams.
  - `packages/screamingface/tests/e2e/harness/goldens.py` — `GoldenModelSpec` (full
    route+prompt+params spec), `kind: "corrective_loop"` + `member_specs`/
    `judge_spec`/`max_rounds` (defaults keep every committed golden valid),
    cross-kind pollution refusal, `spec_model`, loop branch in `build_candidate`.
  - `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — fresh-dump mode
    (`--dump-fresh` + `--candidate`): no capture, no re-key; refuses unless the
    replay reproduces the report's score/coverage/statuses AND rendered expression;
    `author_golden` loop kind; gdpval-text bundle; `_run_gated_bless` split for the
    return budget.
  - `packages/screamingface/tests/e2e/test_boards.py` — `gdpval-text` in `BOARDS` +
    `_ASSET_BUNDLE` (skips loudly until blessed); comment no longer claims the list
    is every registered board (medxpert registered, not onboarded).
  - `packages/screamingface/tests/e2e/README.md` — step ③ (cache env for a local
    recording stack) + step ④ (`just e2e-bless-fresh`).
  - `packages/screamingface/justfile` — `e2e-bless-fresh` recipe.
- **Commits:** (filled by close comment; single commit on OME-1098-goldens)
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GREEN (ruff check,
  format, pyright, pytest 1389 passed / 23 skipped with cov ≥95, notebooks, build,
  distribution).
- **Deviations:**
  - Append-only gate run with `--skip-append-only`: the flagged files are harness/
    tool/fixture code (goldens schema, bless tool, board registration, README), not
    test functions — no prior test was modified or weakened; the extension pattern
    matches OME-978's.
  - No CLI-dispatch unit tests (matches precedent — no sibling mode has them); the
    pure seams carry the contract.
  - Plan named a sha cross-check "before docker boots"; the expression renders only
    engine-side, so the check runs after the verified replay instead — still refuses
    the bless on a drifted candidate spec.

## Follow-up cycle (2026-09-10) — preflight skip + bless diagnosis

- The first bless attempt surfaced that the SDK's free model-parameters preflight
  fires for params-carrying candidates and needs a connected provider — impossible on
  the sealed keyless stack. Owner-approved fix: `SCREAMINGFACE_SKIP_PARAMETER_PREFLIGHT=1`
  (literal "1" only) disarms the preflight; only the replay harness sets it
  (`slice_snapshot._evaluate`, `test_boards`). Two new tests pin both directions; an
  interim throwaway-credential helper was tried, rejected by the gateway's real key
  validation, and removed. `test_boards`'s existing test gained only a `monkeypatch`
  fixture parameter (disclosed prior-test touch; assertions unchanged). Principled
  replacement filed as `OME-1167`.
- The bless then ran and REFUSED correctly: all 39 single-round cases replay
  byte-identically; all 9 multi-round cases miss, because the engine embeds runtime
  accounting (`usage` token counts) inside coach/tie prompts — live counts vs
  cache-hit zeros → different cache keys. Replay proven deterministic (two runs,
  131 identical bodies). Engine defect filed as `OME-1168` (blocks this ticket's
  ifeval bless); after it lands, one owner re-record of the 50-case loop run is
  needed, then `just e2e-bless-fresh` as documented.
- Gates re-run ALL GREEN after the preflight-skip cycle (same `--skip-append-only`
  disclosure).
- 2026-09-10 later: `OME-1167` (keyless model-parameters route) and `OME-1168`
  (minimal coach prompt) merged to main. Branch rebased; the
  `SCREAMINGFACE_SKIP_PARAMETER_PREFLIGHT` hatch, its two tests and both harness
  setters DELETED — a probe bless proved the keyless replay now preflights with no
  hatch (39/50 cases replayed; refusal only on the pre-`OME-1168` recording's stale
  multi-round bytes, as expected). Remaining: owner re-record of the 50-case loop
  run on post-`OME-1168` main, then bless.
- 2026-09-10 later still: owner re-recorded the 50-case loop (score 0.9184,
  coverage 0.98, one `model_token_cap` failed case — a real recurring property of
  the deepseek judge on this board, present in the Sep-9 run too).
  `just e2e-bless-fresh` verified the replay reproduces score/coverage/statuses AND
  the recorded expression, sliced 177 of 226 rows, and wrote the ifeval fixture
  triple; the e2e lane replays `test_boards[ifeval]` green in ~11s, keyless. The
  ifeval manifest gained its `.gitignore` whitelist line (per-board pattern);
  stale example notebooks (owner's recording runs) regenerated via
  `build_notebooks.py`. gdpval-text bless still waits on its fusion recording.
- 2026-09-10 evening: owner recorded the gdpval-text fusion (`open_panel`:
  deepseek-v4-pro + qwen + glm, kimi synthesizer; 25 cases, 3h32m, $17.37; score
  0.8044, coverage 0.8 — 5 failed cases from genuine provider errors during the
  run, pinned as such). `just e2e-bless-report` converged in 4 capture→splice
  rounds and verified the replay reproduces the report exactly; fixture triple
  written (929 rows, 0.46 MB), `test_boards[gdpval-text]` green in ~15s keyless.
  Both goldens of this ticket are now committed; unit DONE pending PR merge.
