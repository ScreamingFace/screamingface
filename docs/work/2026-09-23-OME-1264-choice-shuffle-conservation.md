---
ticket: OME-1264
stack: screamingface-engine
status: in_progress
started: 2026-09-23
finished:
---

<!-- Extension 1 of 2 in progress; ticket stays open for data_files+features and
the 18 board batches. -->

# OME-1264 — Conserve `shuffle_choices` in the inspect importer (extension 1 of 2)

## Intent

Teach the inspect importer + bake to conserve the `shuffle_choices` kwarg of
`hf_dataset` the way `shuffle` already is: pinned by a policy seed and reproduced
in the bake via inspect's own `MemoryDataset.shuffle_choices`, never dropped.
Unlocks the lab_bench ×8 + truthfulqa family (board batches ride later PRs).
This PR is the extension + unit tests only — no boards imported yet.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`
  - `shuffle_choices` joins `_REPRODUCED_DATASET_KWARGS`
  - `TaskFacts`: `upstream_shuffle_choices: bool`, `upstream_choice_shuffle_seed: int | None`
    (bool-before-int check — `True` is an `int`)
  - `main()`: `--choice-shuffle-seed` flag; resolution mirrors `--shuffle-seed`
    (flag wins → upstream int seed → unseeded shuffle with no flag = hard error)
  - `render_fragments`: `{PREFIX}_CHOICE_SHUFFLE_SEED` pin + `choice_shuffle_seed=` SnapshotSpec line
- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`
  - `SnapshotSpec.choice_shuffle_seed: int | None = None`
  - `emit_snapshot`: collect Samples first, apply
    `MemoryDataset(samples).shuffle_choices(seed=…)` once over the whole dataset
    (inspect uses ONE random stream across samples), then validate/render per sample
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py`
  - `_revision_pins` appends `choice_shuffle_seed=N` — the seed rides exam identity
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md`
  - flag doc + refusal-table row ("shuffles choices with no seed → pass `--choice-shuffle-seed`")
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_importer.py` — new tests below;
  `test_introspect_refuses_shuffled_choices` REPLACED (see Deviations rationale)
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_snapshots.py` — bake determinism test

## Test plan

- introspect records `shuffle_choices=True` → fact (shuffles, no seed); `=7` → seed fact 7
- `main` on a choice-shuffling eval without `--choice-shuffle-seed` → error naming the flag
- `main` with the flag → generated fragments carry the `_CHOICE_SHUFFLE_SEED` pin +
  SnapshotSpec line, and the emitted row constructs a real `SnapshotSpec`
- bake with `choice_shuffle_seed` set: choices order == inspect's own
  `MemoryDataset.shuffle_choices(seed)` for the same seed; target letter remapped
  consistently; two bakes byte-identical (INVARIANT: pinned choice order is exam identity)
- `choice_shuffle_seed` appears in `_revision_pins` output
- `shuffle_choices=False`/`None` still imports with no seed demanded

## Acceptance

- `shuffle_choices` conserved: reproduced in generated rows (seeded) or refused by
  name at `main` (unseeded + no flag) — never dropped
- All prior inspect-lane + default-lane tests green; only the one refusal test replaced
- Gates green: `run_gates.py screamingface-engine` + inspect lane
  (`uv run --extra inspect pytest tests/unit/inspect`)

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `_seed_fragments` extracted in importer.py
  (complexity gate) and the bake-determinism test split into its own test
  (statement-count gate). Snapshots test file also gained
  `test_without_a_choice_shuffle_seed_the_choice_order_is_upstreams`.
- **Commits:** `77cd8638` feat(screamingface-engine): conserve shuffle_choices in
  the inspect importer (+ ledger/mirror docs commits on the same branch)
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (ruff check, format, pyright, layering, pytest cov≥80); inspect lane
  `uv run --extra inspect pytest tests/unit/inspect/` 221 passed.
- **Deviations:** `test_introspect_refuses_shuffled_choices` asserted the refusal
  OME-1264 explicitly overturns (acceptance 1: conserve). Replaced by the
  conservation contract tests — the append-only gate was skipped with
  `--skip-append-only` for exactly this one file (documented owner ask: the
  ticket text mandates the behavior change; flagged in the PR body for the
  diff review). NOTE for the owner: the pre-push hook did NOT fire on push
  from this worktree (relative `core.hooksPath` appears not to resolve in
  worktrees — `sh .githooks/pre-push` run by hand correctly exits 1 on the
  append-only check). Gates were run manually instead; the hook quirk is
  process tooling and is left to the owner.

## Review follow-up (owner-approved 2026-09-23, findings on PR #1031)

- Finding 1 resolved by owner: acceptance 1 wins — the refusal moved to
  `main()`; the append-only skip covers only the one replaced test.
- Finding 2 fixed: `--choice-shuffle-seed` over an upstream-SEEDED choice
  shuffle now refuses by name (`_resolved_choice_shuffle_seed` helper carries
  the full flag/fact matrix) + matrix test. The row-shuffle flag keeps its
  pre-existing override behavior — out of scope here.
- Finding 3 fixed: `_shuffle_choices` wraps inspect's shuffle and re-raises as
  a named `PrepareError` (no case number — inspect's loop cannot say which
  sample failed) + test with a non-letter target.
- Gates re-run: ALL GREEN; inspect lane 223 passed. Both new tests appended.

## Review follow-up 2 (blocker, owner-approved 2026-09-24)

- The bake's row shuffle (`random.Random`) is not upstream's (HF
  `Dataset.shuffle`) — same seed, different order — and the choice shuffle
  draws each case's permutation from one stream in row order. Verified by
  repro: 5/8 questions get different choice orders (matches the reviewer).
- Fix chosen: (a) narrow refusal — a choice shuffle COMBINED with a row
  shuffle refuses whenever upstream seeded either one (no fixed upstream exam
  is missed when both seeds are OURS — lab_bench stays importable). Option (b),
  replaying HF's permutation, was declined: it would change the baked content
  of every existing shuffle_seed board (catalogue-wide revision bumps) to fix
  a cell no current import occupies.
- "Reproduces upstream" wording corrected in main()'s row-seed comment, the
  SnapshotSpec field comment, and the snapshot test's docstring (the expected
  helper replays OUR row shuffle — the claim is now scoped to the choice stage).
- Tests: 2 refusal cells + the allowed policy-both cell + the divergence
  witness through the REAL `datasets.Dataset.shuffle` API. Inspect lane 227
  passed; gates green (`--skip-append-only` still covers only the original
  replaced refusal test — the reworded docstring is this PR's own test).
- Pre-existing, out of scope, owner-visible: boards pinning an UPSTREAM row
  seed (no choice shuffle) already don't reproduce upstream's row order —
  their published pinned identity is valid, but the "reproduces upstream"
  belief is false there too. Candidate follow-up ticket.
