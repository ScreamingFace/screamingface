---
ticket: OME-1263
stack: url4
status: in_progress
started: 2026-09-22
finished:
---

# OME-1263 — Restructure url4 by layer: split the hotspot modules, close the vocabularies, enforce the boundaries in CI

## Intent

`packages/url4` had grown modules that each carried several reasons to change
(`dag/nodes.py` at 1062 lines, `cli/_serve.py` at 661, `peer/server.py` at 501,
`dag/executor.py` at 524), a handful of open vocabularies typed as bare `str`, and
duplicated ASGI plumbing across its two entrypoints. Nothing was broken — the suite was
green throughout — but each one made a specific future change fragile, and nothing stopped
the erosion continuing.

Split the hotspots by reason-to-change, close the vocabularies, delete the duplication,
then wire the resulting shape into CI so it cannot silently regrow.

## Planned changes

Reconstructed from the branch's 33 commits (see Deviations — this ledger is retroactive).

- `src/url4/core/errors.py` — `ErrorCode` as `StrEnum`
- `src/url4/dag/nodes.py` → `src/url4/dag/nodes/` package (`fetch` · `group` · `guard` ·
  `iteration` · `_shared`)
- `src/url4/dag/executor.py` → `executor.py` + `dag/_run.py`
- `src/url4/dag/compiler.py` → `_lowering` + `_wiring`; `dag/node.py` → `node` + `_context`
- `src/url4/peer/server.py` → `server.py` + `_http.py` + `_dispatch.py` + `_asgi.py` +
  `_owned.py`
- `src/url4/cli/_serve.py` → `_serve.py` + `_config.py`
- `src/url4/core/subrequest.py` → `src/url4/wire/subrequest.py`
- `src/url4/core/{collection,ensemble}.py` → `src/url4/dag/semantics/`
- `ARCHITECTURE.md` (new); `core`/`io`/`peer`/`cli` package docstrings as front doors
- `scripts/check_module_size.py` (new); `tests/unit/test_layering.py` (new);
  `tests/formal/` models

## Test plan

- `tests/unit/test_layering.py` — import direction over the source AST, including
  function-local and `TYPE_CHECKING` imports. INVARIANT: a layer imports only the layers
  below it.
- `tests/formal/` — breadth-first models of the executor memo and the spawn compile-cache
  atomic check-then-act. Each model is paired: the fixed one must stay clean, the buggy
  one must keep failing, so the checker cannot rot into a no-op.
- Generated-corpus parity (150 grammar-shaped expressions, seed `0x5EED_2026`):
  `compile_expression(text)` ≡ `compile_expression(build(text))`.
- Nested-group parity across five shapes (two-deep nesting, broadcast, outer params),
  mutation-checked: a text-path rename breaks all five.
- `tests/unit/test_front_door_render_blame.py` — the render-blame contract on both front
  doors, plus the two paths that must NOT be re-attributed.

## Acceptance

- `run_gates.py url4` green: ruff · `ruff format --check` · pyright ·
  `pytest --cov=url4 --cov-fail-under=95`.
- Module-size ratchet and layering test pass.
- Every public name still importable from its pre-branch location (facades re-export).

## Deviations

1. **This ledger is retroactive.** The 33 commits were written before the ticket and the
   ledger existed, against SDLC rule 1 ("no code before its ledger"). Filed at the owner's
   instruction once the branch was already complete. The Planned-changes and Test-plan
   sections above are reconstructed from the commit bodies, not written ahead of the work.

2. **Append-only check fails; `--skip-append-only` used.** Six prior test files are
   modified against `main`. Every one is an **import-path rewrite forced by a module
   move** — no assertion, fixture or invariant changed:

   | File | Change |
   |---|---|
   | `tests/spec/test_wire_spec.py` | `core.subrequest` → `wire.subrequest` (14 sites) |
   | `tests/spec/test_mandatory_intent_calls.py` | same, 1 site |
   | `tests/spec/test_processor_delegation.py` | `peer.server._reassemble` → `peer._dispatch.reassemble` |
   | `tests/unit/test_iteration.py` | spy now patches `dag._run` too, after the executor/run split |
   | `tests/unit/test_characterization.py` | additions only (+169/−2) |
   | `tests/unit/test_server.py` | additions only (+48/−2) |

   A refactor that moves a module cannot leave its tests' import lines alone, so this is
   the unavoidable class of prior-test edit rather than a weakened contract.

3. **Two prior tests deleted, with owner sign-off** (commit `80ed2ecd`).
   `test_sequencer_invariant_rejects_a_gap` and `test_obs_state_invariant_rejects_a_gap`
   called the private `_check_invariants` with a fabricated `previous`, so they tested the
   assert expression rather than the producer. Inlining the assert removed the only seam
   they could poke. The externally observable contract stays covered by
   `test_sequencer_numbers_are_gap_free_and_monotonic` and
   `test_obs_state_engine_seq_is_gap_free_and_monotonic`.

   Note: this deletion does **not** itself trip the append-only gate, because its file
   (`tests/unit/test_lifecycle_terminal_frame.py`) was added by this branch in `f312fda2`
   and so is not a prior test relative to `main`. The commit body of `80ed2ecd` claims the
   flag is needed for this change; that is wrong — the flag is needed for the import-path
   rewrites in deviation 2.

4. **Three behaviour changes** in an otherwise behaviour-preserving branch:
   - `5608a5eb` — the SDK front doors skip the verified re-parse (~1.2 ms/call on a
     263-char expression, ~15x the render).
   - `5181d0f3` — `render.verify` made public; `_blaming_render` restores the
     `RenderError` naming the caller's tree, after a `ParseError` has already escaped.
   - `80ed2ecd` — sequence-invariant asserts inlined so `-O` strips them; previously the
     method call was paid on every node finish and every streamed frame.

5. **Card gap found, not fixed here.** `scripts/check_module_size.py` and the formal-model
   suite were added by this branch but never registered in `.claude/sdlc.local.md` under
   the `url4` stack's `gates:`. `run_gates.py url4` therefore does NOT run the ratchet —
   only the GitHub workflow `url4-tests.yml` does. Surfaced per SDLC rule 7 ("verify the
   card's gates cover this skill's categories; a missing category is a card defect").
   Left for the owner: registering a gate changes the contract for every future url4 unit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned above; reconstructed retroactively from the commits.

- **Commits:** 33 on branch `OME-1263-url4-layer-restructure` (renamed from `improve-url4`),
  `f312fda2`..`80ed2ecd`. Not yet pushed; no PR open.

- **Gates:** `uv run .claude/scripts/run_gates.py url4 --base main --skip-append-only`
  → **ALL GATES GREEN** (2026-09-22).

  | Gate | Result |
  |---|---|
  | append-only test check | skipped (`--skip-append-only`; see deviation 2) |
  | `uv run ruff check` | ✓ |
  | `uv run ruff format --check` | ✓ |
  | `uv run pyright` | ✓ 0 errors |
  | `uv run pytest --cov=url4 --cov-fail-under=95 -q` | ✓ **1329 passed**, coverage **98.26%** |

  Run separately, because the card does not list them (deviation 5):

  | Check | Result |
  |---|---|
  | `scripts/check_module_size.py` | ✓ all 17 capped modules within baseline+10 |
  | `tests/unit/test_layering.py` + `tests/formal/` | ✓ 9 passed |

- **Deviations:** see the five above.

- **Open for the owner:**
  1. Close `OME-539` and `OME-546` against this branch — both are delivered.
  2. Decide whether `check_module_size.py` and the formal-model suite become card gates.
  3. The branch is unpushed and has no PR.
