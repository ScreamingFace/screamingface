---
ticket: OME-1115
stack: screamingface-engine
status: done
started: 2026-09-15
finished: 2026-09-16
---

# OME-1115 — Adapter plugin: evaluate a fusion against an imported inspect_evals benchmark

## Intent

Build the engine-side adapter plugin from the OME-1113 spec (§3 + §4): a sealed
`screamingface_engine_inspect` package that wraps one inspect_evals scorer as a board's
`grade_case` hook and registers one imported board (proof board) through a new generic
entry-point discovery seam — engine core gains one discovery loop and zero knowledge of
the plugin's name. This is the epic's deletion-test proof that the `grade_case` seam is
public: a stranger-authored benchmark runs on the shared spine with zero spine edits.

## Planned changes

- `apps/screamingface-engine/pyproject.toml` — optional-dependency group
  `inspect = ["inspect-ai==<pin>", "inspect-evals==<pin>"]`; entry point in the
  `screamingface_engine.benchmark_deployments` group pointing at the plugin's
  registrations.
- Engine core (deployment/composition seam, exact file per recon —
  `benchmarks/deployment.py` or the composition module): one generic entry-point
  discovery loop extending `BUILTIN_DEPLOYMENT`'s registrations; group absent/empty →
  byte-identical behavior.
- `apps/screamingface-engine/src/screamingface_engine_inspect/` — new top-level package:
  - `shim.py` — `inspect_grade_case(scorer) -> GradeCase` (spec §3.2, zero per-scorer
    branches; failure codes `scorer_error`, `invalid_score_value`).
  - TWO proof-board modules (owner decision 2026-09-15, comment on OME-1115):
    `inspect-gsm8k` (free-form, deterministic scorer, check surface declared — proves
    the §4 dual registration + corrective_loop) and `inspect-mmlu` (MCQ, NO check
    surface per the OME-796 elimination-attack rule — proves the refused-loop branch).
  - spec §7 line "OME-1115 proves one board" amended to two in this PR.
  - entry-point target returning an iterable of `BenchmarkRegistration`.
- Tests (append-only):
  - core: discovery loop — empty group → registrations byte-identical to today; a fake
    entry point → its registrations appear.
  - shim: Score CORRECT/INCORRECT/float → CaseGradeOutcome mapping; scorer raises →
    `scorer_error`; unmappable Score.value → `invalid_score_value`; evidence preserves
    the judge's words; non-text envelope kind rejected.
  - layering: `screamingface_engine_inspect` never imported from
    `src/screamingface_engine/` (spec §8.4 grep as a test / check_layering coverage).

## Design decisions (recon 2026-09-15)

- **Discovery seam**: new core module `benchmarks/discovery.py` — reads the
  `screamingface_engine.benchmark_deployments` entry-point group (injectable reader for
  tests); `builtins.py` composes `BUILTIN_DEPLOYMENT` from the static tuple + discovered
  registrations. Empty group → identical tuple.
- **Same-distribution plugin**: the wheel ships both packages, so the entry point always
  exists. The PLUGIN owns its optional deps: `deployment:registrations()` returns `()`
  when `inspect_ai`/`inspect_evals` are not importable (extra absent) — core discovery
  stays generic with no exception policy.
- **Shim + MCQ**: inspect's `choice()` scorer depends on the `multiple_choice` solver
  having marked `state.choices`; the shim's build-TaskState stage replays inspect's OWN
  `parse_answers` + `set_choices_based_on_generated_response` when the board's grading
  material declares `choices`. Their code, keyed off the material shape — still zero
  per-scorer branches.
- **Score mapping**: explicit map (bool, int/float, "C"/"I"/"P"/"N") — NOT inspect's
  `value_to_float`, which silently coerces unknowns to 0.0; unmappable →
  `invalid_score_value`.
- **Proof boards are 0-shot officially-supported parameterizations**: gsm8k
  `fewshot=false`, mmlu `mmlu_0_shot`. Scorers bound directly (`match(numeric=True)`,
  `choice()`) with provenance comments — loading the Task object would download datasets
  at runtime; the importer (OME-1116) does task introspection at import time instead.
- **Revision** = sha256(`inspect-ai==<ver>` + `inspect-evals==<ver>` + dataset pins +
  protocol constants)[:16] from `importlib.metadata` — the exact-pin version string is
  the spec's "pinned package digest" for identity purposes (== pins make them
  equivalent).
- **mmlu snapshot order**: deterministic seeded shuffle at prepare (seed in pins, in the
  revision) so a `limit=N` run spans subjects; dataset order is subject-grouped.
- **Judge routing (§3.3)**: zero code, documented in the plugin package docstring;
  neither proof board is model-graded, so the metered-judge verification rides the first
  model-graded import (OME-1116).
- **Gates without the extra**: plugin tests `importorskip("inspect_ai")` — skipped in
  the plain gate run, executed via `uv run --extra inspect pytest`. The coverage gate's
  `--cov=screamingface_engine` scope is card-owned and untouched.

## Test plan

- RED first per unit: shim tests against a stub scorer (no inspect install needed if the
  scorer protocol is duck-typed; else mark under the `inspect` extra), discovery-loop
  tests with a synthetic entry point, layering guard.
- Full engine suite stays green untouched (zero spine edits is an acceptance bar).

## Acceptance

- One imported benchmark registered and evaluable end to end (paid live run is the
  owner's; agent-side proof = full suite + registration visible + spine untouched).
- `uv sync` without the `inspect` extra installs no inspect distribution.
- `grep -r "screamingface_engine_inspect" src/screamingface_engine/` → empty.
- Zero per-scorer branches in the shim; zero spine edits.

## Outcome

- **Actual files:**
  - Core: `benchmarks/discovery.py` (new), `benchmarks/builtins.py`
    (STATIC_REGISTRATIONS + discovered composition), `pyproject.toml` (== pins, entry
    point, wheel packages), `uv.lock`.
  - Plugin `src/screamingface_engine_inspect/`: `__init__.py`, `deployment.py`,
    `boards.py`, `shim.py`, `pins.py`, `envelopes.py`, `prepare.py`, `single_shot.py`.
  - Tests (new): `test_inspect_deployment_discovery.py`, `test_inspect_shim.py`,
    `test_inspect_gsm8k_board.py`, `test_inspect_mmlu_board.py`.
  - Tests (amended, owner-approved 2026-09-16): `test_benchmark_deployment.py`
    (family guard → STATIC_REGISTRATIONS), `test_benchmark_declaration.py` (explicit
    plugin rows, required only when installed), `test_url4_executor.py` (plugin
    packages are Benchmark extensions).
  - Spec §7 amended: OME-1115 proves two boards (owner comment 2026-09-15).
- **Commits:** 66e97ec4 discovery seam · a105543d shim · (final commit: boards +
  amendments — sha in the close comment).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (2924 passed, 9 skipped; the skip covers exactly the three owner-approved test
  amendments). Extra-less contract verified: `uv sync` without the extra installs no
  inspect distribution, `BUILTIN_DEPLOYMENT.registrations == STATIC_REGISTRATIONS`,
  and `grep -r screamingface_engine_inspect src/screamingface_engine/` is empty.
- **Deviations:**
  - **Scope re-carve (owner decision 2026-09-16).** The per-board modules
    (`gsm8k.py`/`mmlu.py`, PRs #955/#956) were closed unmerged — one Python file per
    benchmark doesn't scale to the ten-board import. This ticket's merged output is
    the import infrastructure (#951–#954); the two proof boards land as `BoardSpec`
    ROWS in `boards.py` via OME-1116's first PR, which also carries this Outcome and
    the mirror close.
  - **Two-session collision.** A second session built the proof boards concurrently in
    this worktree; resolved by yielding it the plugin layout (`pins`/`envelopes`/
    `prepare`/`single_shot`), then merging: this session's committed discovery seam +
    shim underneath, its test suites ported onto the final layout, the per-board
    installer/`ASSET_BUNDLE_ID` conformance fix, and the lazy shim import that keeps
    `inspect_ai` (and its OTel/web deps) out of the run mode's cold-start import
    budget. Its RED sketch `test_inspect_boards.py` was deleted after its assertions
    were folded into the final suites.
  - Judge routing (§3.3) is documented config only — neither proof board is
    model-graded; the metered-judge verification rides the first model-graded import
    (OME-1116).
  - `origin="inspect_evals"` not set: the field lands in OME-1112 (unmerged); one-line
    follow-up in `single_shot_board` once it merges.
  - The paid `limit=50` acceptance run is the owner's; agent-side proof = full suite +
    registrations + zero spine edits (`git diff` touches no `benchmarks/spine/` file).

Status: DONE (pending PR review + owner's paid run).
