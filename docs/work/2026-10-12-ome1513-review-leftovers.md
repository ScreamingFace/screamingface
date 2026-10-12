---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# ome1513-review-leftovers — close three review leftovers from OME-1513 (Work order #5)

## Intent

OME-1513 turned the Draft Feedback offer off on the three hand-built rubric Benchmarks (draco,
gdpval, healthbench), but each still installed its check-surface route, so a raw url4 string sent
to the Engine (skipping the SDK's Corrective-Loop refusal) could still buy a paid Judge pass on a
Benchmark whose offer is off. This unit installs that route only when the Benchmark carries the
offer, the same gate the inspect plugin already applies, and fixes two stale lines left by the
same review. A third leftover (MuSiQue's support-F1 scorer failing loudly on missing metadata)
was held: see Deviations.

## Planned changes

- `benchmarks/{draco,gdpval,healthbench}/runtime.py`: install the check-surface route only when
  `draft_feedback=True`; `variant.py` of each passes `benchmark.check_surface is not None`.
- Delete `tests/unit/test_draco_corrective_loop_e2e.py` and `tests/unit/data/draco_corrective_loop_candidate.url4`.
- `tests/unit/test_benchmark_stage_parity.py`: take DRACO's stand-in assets from `test_draco_case_artifacts.py`.
- `tests/unit/test_draco_3pass_definition.py`: the two check routes are asserted absent, not present.
- `tests/unit/test_draft_feedback_offer_is_owner_opt_in.py`: one new pin test.
- `docs/adding-a-benchmark-manually.md`: drop "draco's passes" from the multi-call exception.
- `src/screamingface_engine_inspect/benchmarks.py`: the gsm8k row comment says no offer.

## Test plan

- `test_an_offer_that_is_off_is_not_reachable_by_url4_string`, parametrized over every hand-built
  Benchmark with no offer: installs it into an empty world and asserts no `/check-surface` route.
  Red on the old runtimes for all five rubric boards, green after.
- The kept check-surface marking tests (`test_draco_check_surface.py`,
  `test_healthbench_check_surface.py`) install the endpoint on their own node and stay unchanged.

## Acceptance

- No published revision moves (`test_published_revisions.py`, the definition tests green).
- No hand-built Benchmark with its offer off installs a check-surface route.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the three `variant.py` comments that said the route "is
  still served" now say it is not installed, and the approval manifest
  `.claude/test-change-approvals/OME-1527.json`.
- **Commits:** this branch, `OME-1527-pr5-ome1513-leftovers`.
- **Gates:** relevant tests only — the check-surface, definition, runtime, stage-parity,
  stage-installation, published-revision and declaration tests (216 passed); ruff and
  extra-less pyright clean on every touched file. Pre-push `run_gates.py screamingface-engine`:
  ALL GATES GREEN (append-only check included).
- **Deviations:** the MuSiQue leftover is NOT in this unit. Making `musique_support_f1` raise on
  a missing `supporting_idx` edits `local_tasks/musique/musique.py`, and the MuSiQue revision
  hashes every `.py` file in that package, so its published revision moves (probe:
  `test_published_benchmark_revision_is_byte_identical[musique-1ae798e073477a54]` fails). The
  work order said to stop and report rather than re-pin. The owner then approved the move, and
  it ships stacked on this PR as #1354 (ledger `docs/work/2026-10-12-musique-loud-scorer.md`).
