---
ticket: OME-1513
stack: screamingface-engine
status: done
started: 2026-10-07
finished: 2026-10-07
---

# OME-1513-pr1-musique-local-task — MuSiQue-Ans as the first local inspect Task

## Intent

Serve MuSiQue-Ans through the import lane from a Task we author ourselves (not in
inspect_evals), proving the lane rule "a new Benchmark is one Task file" on a real
Benchmark, and folding in the two things the 2026-10-07 spike (`spike-musique-local-task`,
`aaba12596`) found missing: a row-level `origin` so a local Task needs no inspect porter
list, and a scorer that tolerates absent Sample metadata.

## Planned changes

- `src/screamingface_engine_inspect/local_tasks/__init__.py`, `local_tasks/musique/__init__.py`
- `src/screamingface_engine_inspect/local_tasks/musique/musique.py` — the Task (loader, reply
  reader, three scorers, `@task`)
- `src/screamingface_engine_inspect/local_tasks/musique/vendor/` — the paper's scorer, copied
  verbatim from StonyBrookNLP/musique@922ac98f (CC BY 4.0) with its LICENSE
- `src/screamingface_engine_inspect/local_tasks/musique/README.md` — bbeh-style card
- `src/screamingface_engine_inspect/benchmarks.py` — `BenchmarkSpec.origin` (default
  `inspect_evals`), the generated `musique` row with origin `screamingface`
- `src/screamingface_engine_inspect/single_shot.py` — `origin` parameter passed through
- `src/screamingface_engine_inspect/prepare.py` — the generated `musique` Task-replay row
- `tests/unit/inspect/test_local_task_musique.py` — new
- `tests/unit/inspect/test_benchmark_declaration.py`, `test_inspect_imported_benchmarks.py`,
  `test_published_revisions.py` — one table row each
- `docs/adding-a-benchmark-manually.md`, `docs/adding-an-imported-benchmark.md` — lane rule,
  local-Task recipe, network gotchas
- `docs/tasks/2026-10-07-OME-1513-local-task-benchmarks.md` — mirror

## Test plan

- RED: `test_local_task_musique.py`
  - conservation: the Benchmark's grade hook returns, for three canned replies, exactly the
    numbers the paper's own `AnswerMetric` / `SupportMetric` give (happy, partial, no labels)
  - the reply reader: last label wins, markdown-wrapped label, label alone on its line,
    no label at all, labels in either order
  - prompt bytes: a synthetic row renders to a pinned literal
  - absent Sample metadata never raises; the paper's metric scores it (0.0 if the reply cites, 1.0 if not)
  - the row declares origin `screamingface`, no porter list, and `provenance_gaps` is empty
  - Named Scores in the published order, answer F1 the headline
- RED: `BenchmarkSpec(origin="screamingface")` assembles a Benchmark whose `origin` is
  `screamingface`; the default stays `inspect_evals`
- Table rows: declaration policy, family, published revision literal

## Acceptance

- `musique` registers from the local Task with 3 Named Scores; prepare matches the
  Case Digest; the inspect lane and the Engine gate are green
- Both onboarding docs carry the lane rule and the local-Task recipe
- No hand-built `benchmarks/musique/` folder exists

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `pyproject.toml` (vendor dir excluded from ruff, format and
  coverage), `tests/unit/inspect/test_local_task_musique_vendor.py` (the vendored scorer's
  sha256 pins, ported from the closed hand-built PR) and
  `.claude/test-change-approvals/OME-1513.json` (one amended assertion + two table rows).
- **Commits:** see the PR; one squash.
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only with the OME-1513
  approval, ruff, format, pyright, layering, pytest with coverage ≥ 80); inspect lane 1,280 passed
  on the way.
- **Review fix (pre-merge review, 2026-10-07):** a local Task's grading code was not part of
  its revision (an import's is, via `inspect-evals==`). `local_tasks/__init__.py` now hashes
  every `.py` under the Task's package (`vendor/` included) into a `task_source=` pin that
  `_task_replay_pins` appends for local-Task rows only; the revision moved once to
  `958386b03c1288e7`; pinned by a one-byte-moves-the-digest test and an uppercase-label reader
  case (the reviewer's IGNORECASE mutation had passed the lane). `hop_type` now rides the
  headline Score's metadata into the Report; an AIDEV-NOTE above the frozen-name test says
  what it checks now. The continuous `satisfaction` on Draft Feedback is lane-wide (squad
  exposes F1 the same way) and is left for the owner on the ticket.
- **Owner rule folded in (2026-10-07): Draft Feedback is opt-in per Benchmark, never a default.**
  The importer no longer emits the field at all (it defaults to False on the row type, where the rule now lives); the nine imported rows that carried the
  offer by family rule (gsm8k, paws, boolq, aime24, aime25, mgsm_en, bbeh, squad, math) and the
  three hand-built rubric Benchmarks (gdpval, draco, healthbench: `check_surface=None`, route
  still served) turn it off; IFEval is the one Benchmark with the offer, and says why. Nine
  imported revisions moved once (no external users); hand-built revisions unchanged. Twelve
  prior test files amended in the OFF direction, pinned in the approval manifest.
- **Deviations:** the prior assertion "every plugin benchmark came from inspect_evals" is
  amended to "origin matches where the task code lives, both ways" — a Confidence-Gate edit,
  pinned in the approval file and flagged in the PR for the owner to confirm. The importer was
  run twice (spike path, then final path); only the final rows ship. Network workarounds
  (`HF_HUB_DISABLE_XET=1`, IPv4-only name resolution) were needed on the dev Mac and are
  documented, not coded.
- **CI fix (2026-10-08):** the amended declaration test told plugin rows apart by assembling
  them (`benchmark_registrations()`), which reads inspect-ai's installed version; CI's unit lane
  has no inspect extra, so it raised `PackageNotFoundError` while the local gate (venv with the
  extra) was green. It now derives the ids from the spec rows; verified in an extra-less venv
  (pyright clean, 4,616 unit tests passed) and re-pinned in the approval manifest.
- **Vendored headers (owner rule, 2026-10-08):** each file under `vendor/` now opens with our
  own docstring linking to its upstream blob at the pinned commit; the authors' docstrings are no
  longer repeated as ours. The pin test drops the header before hashing (upstream code sha256,
  not file sha256). The `task_source` digest moved with it: musique revision `67d3fc96ffc68e46`
  → `1ae798e073477a54`.
- **Review fixes (2026-10-08, second external review):** notebook 09 rebuilt IFEval-only and
  notebook 12's boolq paragraph corrected (both ran or described loops now refused); the PR
  TLDR names the 14 Benchmarks that refuse a loop and the nine revision moves; a catalogue-wide
  test pins "only IFEval offers Draft Feedback"; the support-F1-without-metadata claim corrected
  from 0.0 to the paper's rule (0.0 citing, 1.0 not) with a test for both; the `task_source`
  pin now covers every Task not under `inspect_evals` and refuses an empty package; the origin
  rule is "inspect_evals iff the task lives there". Rubric-board route gating stays a follow-up.
- **Owner-verify:** one paid run of a solo Candidate on `musique` to see real numbers
  beside the 0.692 Frontier Score; the amended assertion in
  `test_inspect_imported_benchmarks.py`.
