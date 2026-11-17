# Plan — FutureX-Past as a local inspect Task

Spec: `docs/spec/2026-11-16-futurex-past-local-task.md`. Ledger:
`docs/work/2026-11-16-futurex-past-local-task.md`. Worktree `.claude/worktrees/futurex-past-local-task`,
branch `futurex-past-local-task` from `origin/main@66962a178`. Loop: `sdlc-python`, which writes a
failing test first, keeps tests append-only, and stops hard after 10 failed fix attempts.

Paths below are relative to `apps/screamingface-engine/` unless they start with `packages/` or
`docs/`.

## Files

| File | New/edit | What |
|---|---|---|
| `src/screamingface_engine_inspect/local_tasks/futurex_past/__init__.py` | new | empty package |
| `…/futurex_past/futurex_past.py` | new | pins, loader, reply reader, level-1/2 rules, `@task`, `futurex_score` scorer, `futurex_tier_weighted` metric (≤450 lines, otherwise split as below) |
| `…/futurex_past/grading.py` | new | the level-3/4 logic: number parsing (`to_float` rules), the judge prompts (ours), the router, ranking/unordered/number/string scores. Kept apart so `futurex_past.py` stays small |
| `…/futurex_past/futurex_past_study.py` | new | spec §10: the second `@task` (pin `3c2e3969`), the study scorer and the study tier-weighted metric, reusing the shared loader and reply reader |
| `…/futurex_past/vendor/study_metrics.py`, `vendor/__init__.py` | new | the study's `metrics.py`, byte for byte below our header |
| `tests/unit/inspect/test_local_task_futurex_past_study.py` | new | the study Task's contract, the 100 positions ↔ study `item_id`s, and the vendor sha256 |
| `tests/unit/inspect/test_futurex_past_study_replication.py` + `tests/fixtures/futurex_past_study/*.json` | new | spec §10.4: 3 complete-coverage models plus the fused-medoids decisions; scores equal the study's, and 0.302 |
| `…/futurex_past/README.md` | new | the card: dataset, prompt, scoring table with links to Futurex-Eval@2626f7a2 file:line, upstream notes, named deviations, contamination caveat, how to run |
| `src/screamingface_engine_inspect/prepare.py` | edit (importer) | generated Case Preparation entry |
| `src/screamingface_engine_inspect/benchmarks.py` | edit (importer + hand) | the row: provenance (paper, authors, citation, Apache-2.0, baselines, difficulty), `JudgeSpec` house judge + deviation note, `failure_policy="withhold"`, Draft Feedback off, `published_revision`, `notebook=` |
| `tests/unit/inspect/test_local_task_futurex_past.py` | new | the Task's own contract (below) |
| `tests/unit/inspect/test_futurex_past_grading.py` | new | the level-3/4 rules against a scripted judge (no network) |
| `tests/unit/inspect/replayed_cases_helpers.py` | edit | `STAND_IN_METADATA["futurex_past"]`, realistic level-3 metadata |
| `tests/unit/inspect/test_benchmark_declaration.py`, `test_inspect_imported_benchmarks.py`, `test_failure_policy_rows.py`, `test_published_revisions.py`, `test_benchmark_fingerprints.py` | edit | one row each (plus the row counts the failure-policy invariant asserts), as hle_diamond and medmcqa did |
| `packages/screamingface/scripts/build_notebooks.py`, `packages/screamingface/examples/21_futurex_past.ipynb` | edit/new | the example notebook (generated, output-free) |
| `docs/benchmarks-fidelity/futurex_past.md` (under `apps/screamingface-engine/docs/`) | new | the Fidelity Record from `sf-benchmark-fidelity` |
| `CHANGELOG.md` (Engine) | maybe | only if new Benchmarks get a line (to check against the hle_diamond precedent) |

## Steps

1. **RED: the Task contract** (`test_local_task_futurex_past.py`), using a small in-repo parquet
   fixture built in the test from four hand-written rows (one per level, including a duplicate id
   and the `[Yes]` row). No network.
   - the loader refuses a wrong sha256; the pins equal the spec's commit, file and sha256
   - `input` is the row's `prompt` byte for byte; `target` is the parsed list; `[Yes]` becomes `["Yes"]`
   - Case ids are `<id>@<YYYY-MM-DD>` for all three `end_time` shapes, and duplicate ids get
     distinct Case ids
   - the metadata keys are exactly those in the spec
   - the Task is `generate()` with one scorer and the tier-weighted metric
2. **RED: the reply reader and level 1–2 rules.** The last box wins; nested `\text{}` boxes;
   no box gives no answer and 0.0; commas split; label normalisation (letters, Yes/No, quotes,
   wrapper); single gold is exact, several golds give set F1 (partial, wrong, empty, extra).
3. **RED: levels 3–4** (`test_futurex_past_grading.py`), with a scripted fake judge model.
   - Numbers: a clean number skips the judge; free text asks the judge; `None` gives 0; σ = 5% of
     gold, or 0.01 at gold 0; a negative gold works; the clamp holds at 0; the score is exactly 1
     when equal.
   - Strings: the judge's yes/no maps to 1/0; the first comma piece is what gets judged.
   - Lists: the router is called once and its three routes are honoured; the contract-conflict
     short-cut skips the router; the option-token sorted short-cut skips the judge; ranking
     partial credit is 0.8·m/k; unordered gives 1.0 only when m = k = |prediction|, and
     case-folded set equality skips the judge.
   - Unparseable judge replies go through the redraws to `JudgeReplyUnparseable`.
4. **RED: the metric.** All four levels give Σ w·mean. A missing level renormalises the weights.
   No metadata gives the plain mean. A hand-computed example from the study's `tier_weighted`
   matches.
4b. **RED: the study Benchmark** (spec §10). The loader reads the `3c2e3969` schema (integer
   `level`, no `std`). The 100 positions map to exactly the study's `item_id`s. The vendored file's
   sha256 is pinned. Per-Case scores come from the vendored `item_score` after `normalise`. The
   replication fixture reproduces each model's `futurex_score` exactly, and fused-medoids gives
   0.302. The fixtures are generated once from the study package by a script kept in `.docs/` (not
   committed); the PR names the generating command.
5. **GREEN**: write `futurex_past.py`, `grading.py` and `futurex_past_study.py` until steps 1–4b pass. Every rule carries a
   `WHY:` or `INVARIANT:` anchor naming the official file:line it mirrors.
6. **Import.** Run
   `uv run python -m screamingface_engine_inspect.importer screamingface_engine_inspect.local_tasks.futurex_past.futurex_past:futurex_past --key futurex_past --whole-run-metric honour`
   (with `HF_HUB_DISABLE_XET=1` if the Hub stalls). Run it again for
   `futurex_past_study:futurex_past_study --key futurex_past_study --whole-run-metric honour`.
   For both rows, fill every TODO in the generated row by
   hand, set `origin="screamingface"`, and add the JudgeSpec and the deviation notes.
7. **Shared tables**: stand-in metadata plus the five per-Benchmark tables. Use
   `just engine benchmark-bump futurex_past` for the revision and fingerprint literals.
8. **Notebook**: add a `_futurex_past_e2e()` builder modelled on frames'. It runs `futurex_past`,
   then `futurex_past_study` on the study's 100 positions (`cases=[...]`). Regenerate it, and check
   that `check_notebooks.py` passes.
9. **README card.**
10. **Gates.** Run `uv run .claude/scripts/run_gates.py screamingface-engine` and
    `… screamingface`. The append-only check is expected red **only** for the table files the
    spec §9 lists, because no `OME-N` approval file exists. Because the runner stops at the first
    red gate, each remaining gate of both stacks is also run by hand and must be green. The
    10-attempt cap applies per failing signal.
11. **Review.** Run the `sf-benchmark-fidelity` agent and write the record; fix or declare its
    findings. Then run `sf-code-review` on the diff and fix its findings.
12. **Ledger outcome, then commit**: one conventional commit,
    `feat(screamingface-engine): serve FutureX-Past as a local Task`, plus follow-ups for the
    record and review fixes. No `Co-Authored-By`.
13. **PR draft**: written to `.docs/pr-futurex-past.md` (gitignored) with the summary, test plan,
    the "Linear skipped" note, the cross-cutting note, and the approval-manifest JSON ready to
    commit. **Stop.** Push or open the PR only on the contributor's OK.

## Risks

- **Importer replay and network.** The loader reads one 477 KB parquet. If the clean child
  cannot reach the Hub, apply the doc's IPv4 shim.
- **The judge's cost at grading.** Up to about 3 judge calls per level-3/4 Case (664 Cases),
  and none for levels 1–2.
- **Router variance.** It is uncached across runs (spec §4.2). Temperature 0 limits it; the
  README states it.
- **pyright without the inspect extra.** Both new modules open with the file-level
  `reportMissingImports=false` header, as musique does.
