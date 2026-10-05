# One Case Preparation path (OME-1460) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. **Task 0 runs before any code** and may change the
> spec's R12 table; stop and amend the spec if it does.

**Goal:** Prepare every Imported Benchmark by Task replay with capture: the recorder enforces
the declaration's Hub revision and seeds on the eval's own fetches, the 28 Hugging Face-path
rows are re-imported as `TaskReplayCasesSpec` rows with new Benchmark Revisions under their
keys, and the Hugging Face reader, registry, writer and lockfile are deleted.

**Spec:** `docs/spec/2026-10-02-ome-1460-one-fetch-path.md` (R1–R20, D1–D8, F1–F7). This plan
starts after the owner approves it.

**Ticket:** [OME-1460](https://linear.app/openmined/issue/OME-1460/prepare-every-imported-benchmarks-cases-by-calling-the-evals-own-task),
sub-issue of OME-1273. Epic OME-1299. Ledger of this spec unit:
`docs/work/2026-10-02-ome-1460-one-fetch-path-spec.md`; each PR below opens its own ledger.

**Architecture:** `case_sources.py`'s recorder grows an enforcer: a wrap on `hf_dataset` (real
and shim, by identity) that forces `revision`, `seed` and `shuffle_choices` from the
declaration, and a revision check on the three Hub primitives it already wraps. Both children
(`import_replay.py`, `task_replay.py`) install it. `TaskReplayCasesSpec` carries the pins and
the two row options that only `CasesSpec` had (`excluded_sample_ids`, `needs_hf_token`);
`_task_replay_pins` adds the source pins to identity. The importer keeps only its Task-replay
path. `prepare.py` loses the Hugging Face writer and `BENCHMARK_CASES`; `pins.py` goes.

**Tech Stack:** Python 3.12, uv, pytest, `inspect-ai` 0.3.263, `inspect-evals` 0.20.0,
`datasets` 5.0.0, `huggingface_hub`.

## Global Constraints

- One worktree per PR, off `upstream/main`:
  `git worktree add .claude/worktrees/<slug> -b <slug> upstream/main`; rename to
  `OME-1460-<slug>` at PR-open. The remote is `upstream`.
- All paths are relative to `apps/screamingface-engine/` unless they start with `docs/`.
- `uv sync --extra inspect --inexact` once per worktree, then `uv run pytest <path> -q`.
- Gates before each PR, from the repo root: `uv run .claude/scripts/run_gates.py screamingface-engine`
  (append-only test check, ruff, format, pyright, layering, pytest with coverage ≥ 80). Read
  the exit code; never pipe the runner into `tail` inside a `&&` chain.
- **Sequencing against OME-1273 step 7** (sad, bbeh, cyberseceval_4, pre_flight, chembench;
  worktree `task-replay-benchmarks-3`, at `main` with no commits on 2026-10-02): PR A may
  merge before it. PR B rebases onto step 7's merged rows and merges after, because it writes
  at the `TASK_REPLAY_CASES` and `BENCHMARKS` anchors step 7 writes to, and its R15 lane and
  acceptance counts include step 7's Benchmarks. If step 7 stalls, the owner
  decides which goes first; the plan does not.
- Glossary words only (`CONTEXT.md`): Case, Case Preparation, Case Source, Case Digest, Grading
  Material, Benchmark key, Answer key, Imported Benchmark, Named Deviation, Task replay. Never
  "board", "bake", "exam", "row" for a Case, "sample" for a Case.
- Plain `test_` functions. Type every argument, return value and non-obvious local. Every
  function gets a one-sentence intuition docstring; the enforcer gets the Feynman treatment.
- Tests are append-only across commits. A prior test is edited or deleted only with the
  owner's `--skip-append-only`, asked for by name: PR B needs one (see Owner presses).
- Commits: conventional, `feat(screamingface-engine): …` / `refactor(…)` / `docs(…)`, no
  `Co-Authored-By`. Stage explicit paths, never `git add -A`.
- Files that import `inspect_ai` or `inspect_evals` carry the file-level
  `# pyright: reportMissingImports=false` header with its WHY comment.
- Nothing in any test touches the network. Enforcer and replay tests use a stand-in eval
  written to `tmp_path` and put on `PYTHONPATH`, the pattern in
  `tests/unit/inspect/test_task_replay.py` and `test_import_replay.py`.
- Paid model runs are the owner's. Nothing here calls a model. The re-imports download
  datasets (free) on the importing machine; xstest needs `HF_TOKEN` there.

## Decisions taken in this plan (owner can flip any before coding starts)

The spec's D1–D8 are design decisions. These are delivery decisions.

| # | Decision | Why | Flip means |
| -- | -- | -- | -- |
| P1 | **Task 0's sweep is a script under `scripts/` committed with PR A**, not a one-off | the same diff (today's `cases.json` vs the replayed one, by id and by text) is the F5 evidence for every row, and a dependency bump will want it again | a throwaway script in the ledger |
| P2 | **The enforcer lives in `case_sources.py`** as part of `CaseSourceRecorder` (`install(pins=…)`), not a new module | one customs officer at every door; the wrap list and the rebind-by-identity logic already live there | `fetch_pins.py` with its own install |
| P3 | **Pins reach the child through the declaration file** (`spec.json` / `request.json` already carry the declaration's fields) | no new protocol; the image-side child already reads the whole declaration | a separate pins file |
| P4 | **The what-changed note is a comment line on the row**, `# Fold (OME-1460): …`, written by the dev from the sweep's output | the row is where the reviewer reads provenance today | a table in the PR body only |
| P5 | **PR B lands the 28 rows in two commits (unseeded half, then seeded half) and the deletion in a third**, one PR | owner's call 2026-10-05 (spec D5): one review, one `--skip-append-only` press, one step-7 rebase; the commit split keeps the diff readable by half | four stacked PRs |
| P6 | **Seed values are today's** (`COMMONSENSE_QA_SHUFFLE_SEED` etc. become the row's `shuffle_seed=`) | the diff reads "same seed, inspect's algorithm" | fresh seeds |

## Review Focus

1. **The enforcer sees a name bound before it installs.** gsm8k does `from inspect_ai.dataset
   import hf_dataset` at import; `_rebind_everywhere` must catch it and the shim. Pinned in
   Task A2 (`test_the_enforcer_rebinds_hf_dataset_imported_by_name_and_the_shim`).
2. **A forced revision reaches `datasets.load_dataset`, not only `hf_dataset`.** inspect's
   `hf_dataset` passes `revision` straight through (`hf.py:215`) and bypasses its own disk
   cache whenever `revision` is set (`hf.py:204`); the child's caches are empty anyway. Pinned
   in Task A2 (`test_a_missing_revision_is_replaced_by_the_pin_before_load_dataset_runs`).
3. **A different sha is refused, a branch name is replaced.** Pinned in Task A2 (two tests).
4. **A seeded upstream call is never touched.** mmlu passes `seed=42`; gsm8k's few-shot load
   passes `fewshot_seed`. Pinned in Task A3 (`test_a_seeded_upstream_shuffle_keeps_its_seed`).
5. **`shuffle_choices=True` becomes the int seed, `False` stays `False`.** Pinned in Task A3.
6. **The image-side child enforces too.** A declaration with a pin must produce the same
   digest from `replayed_cases` as from `replay_for_import`; a stand-in eval that shuffles
   unseeded must agree across the double run only because both children forced the seed.
   Pinned in Task A4 (`test_the_second_run_forces_the_same_seed_as_the_first`).
7. **The gated skip writes no `unconfirmed_cases` key.** Otherwise every secretless PR's
   strict image job fails on xstest. Pinned in Task A5.
8. **An excluded id that is absent refuses.** The existing `_without_excluded_samples` rule,
   now reached from the child. Pinned in Task A6.
9. **The source pin joins identity only when non-empty.** The 16 URL-only Task-replay rows
   keep their revisions byte for byte; `test_published_revisions.py` does not pin them, so
   Task A7 adds a test that reads each of the 19 current declarations and asserts the
   revision is unchanged for the URL-only ones.
10. **lab_bench's answer position.** After PR B, no lab_bench row has its target at one letter
    for every Case. Pinned in Task B4.
11. **The question filter keeps the same ids.** Task 0's sweep output for onet_m6, pubmedqa,
    xstest ×2 is the evidence; Task B2 records it in the ledger (R13).

## Task 0: The refusal sweep (before any code)

**Files:**
- Create: `scripts/sweep_task_replay_fold.py` (P1)
- Ledger: the PR A ledger, section "Task 0 sweep"

What it does, per key in `BENCHMARK_CASES` (28): (1) prepares today's Cases with
`prepare_cases` into a scratch dir; (2) runs `import_by_task_replay` with the task reference
and task args the row implies (`fewshot=0` for gsm8k and winogrande, `subset=` for xstest;
`--shuffle-seed`/`--choice-shuffle-seed` as today's row has them, so the enforcer of Task A3 can
be tried once it exists; before it exists, record the refusal); (3) records one line: key,
`imported` or `refused: <reason>`, Case count today vs replayed, the set of Sample ids
(identical / differs), and the text verdict (identical / order only / N Cases differ, with
the first differing Case's diff). Hub Case Sources recorded without a revision are listed
too (D4's list).

- [ ] **Step 1: Write the script** (no test: it is evidence tooling, not production code; it
  imports only existing functions).
- [ ] **Step 2: Run it on a dev machine with `HF_TOKEN` exported**, twice: once on `main`
  (every row that shuffles unseeded upstream should refuse with "two Task replays produced
  different Cases", lab_bench ×6 among them; gsm8k and winogrande should import at
  `fewshot=0`; musr and xstest should import with a text change), and once after Task A3 on
  the PR A branch (every row should import). Record both outputs in the PR A ledger.
- [ ] **Step 3: Reconcile with the spec's R12 table.** Any row whose verdict differs from
  the table amends the spec in the same PR (a row that refuses for a reason the spec does not
  name is a STOP: ask the owner before coding around it).
- [ ] **Step 4: Commit**

```bash
git add apps/screamingface-engine/scripts/sweep_task_replay_fold.py docs/work/<pr-a-ledger>.md
git commit -m "chore(screamingface-engine): sweep the 28 Hugging Face-path rows under Task replay"
```

---

## PR A — the enforcer and the declaration (branch `one-fetch-path-enforcer`)

Spec R1–R9, D1, D6, D8 (the fields only). No real Benchmark moves; every existing revision
is byte-identical after this PR (Review Focus 9).

### Task A1: Ledger

- [ ] `docs/work/2026-10-0X-one-fetch-path-enforcer.md` from `docs/work/TEMPLATE.md`,
  `ticket: OME-1460`, Intent from this PR's heading, Planned changes = Tasks A2–A7's files,
  Test plan = the test names below, Acceptance = spec acceptance 4, 6 (first half), 7
  (second half), status `in_progress`. Commit.

### Task A2: The enforcer forces the revision (R1, R2)

**Files:**
- Modify: `src/screamingface_engine_inspect/case_sources.py` (`CaseSourceRecorder.install`
  takes `pins: FetchPins | None`; a `FetchPins` frozen dataclass: `source_pins`,
  `shuffle_seed`, `choice_shuffle_seed`; a `_force_revision` step inside `_wrap`, keyed by
  the repo id each `describe` already derives)
- Test: `tests/unit/inspect/test_case_sources.py` (append)

- [ ] **Step 1: Write the failing tests** — a stand-in `hf_dataset` call with no revision
  receives the pin (`test_a_missing_revision_is_replaced_by_the_pin_before_load_dataset_runs`,
  asserting on the `load_dataset` kwargs the wrap forwards); a branch name is replaced; a
  different sha raises `CaseSourceError` naming both shas (F2); a repo with no pin raises
  naming the repo (F1); the real `inspect_ai.dataset.hf_dataset` and the inspect_evals shim
  are both rebound (`test_the_enforcer_rebinds_hf_dataset_imported_by_name_and_the_shim`);
  `snapshot_download` and `hf_hub_download` get the same revision rule.
- [ ] **Step 2: Run, confirm they fail for the right reason** (no `pins` parameter).
- [ ] **Step 3: Implement**, with the Feynman docstring: mental model (a customs officer who
  also stamps the visa the traveller forgot), the stages, and the worked example (gsm8k's
  call already carries `cc7b047b…`, so stage 2 passes it through).
- [ ] **Step 4: Run the whole `tests/unit/inspect/` lane green.** Commit.

### Task A3: The enforcer forces the seeds (R3, D1)

**Files:**
- Modify: `case_sources.py`
- Test: `tests/unit/inspect/test_case_sources.py` (append)

- [ ] **Step 1: Write the failing tests** — `shuffle=True` with no `seed` receives
  `shuffle_seed`; `shuffle_choices=True` becomes the int `choice_shuffle_seed`;
  `shuffle_choices=False` and a seeded call are untouched
  (`test_a_seeded_upstream_shuffle_keeps_its_seed`); `shuffle=True` with no seed and no
  declaration seed raises naming the call (F6); `shuffle=False` never gains a seed (the
  enforcer never adds a shuffle).
- [ ] **Step 2: Fail for the right reason. Step 3: Implement. Step 4: Lane green. Commit.**

### Task A4: Both children install the enforcer (R4, R5)

**Files:**
- Modify: `src/screamingface_engine_inspect/task_replay.py` (`_replay_in_this_process`
  installs the recorder with the declaration's pins, records nothing),
  `src/screamingface_engine_inspect/import_replay.py` (passes the pins from `request.json`;
  `import_by_task_replay` takes the seeds from the CLI and writes `source_pins` from the
  recorded Hub Case Sources, then the second run reads them off the declaration)
- Test: `tests/unit/inspect/test_task_replay.py`, `test_import_replay.py` (append)

- [ ] **Step 1: Write the failing tests** — with the stand-in eval's unseeded four-row
  shuffle (the one `test_import_replay.py` already uses to prove refusal), passing
  `shuffle_seed` makes the double run agree
  (`test_the_second_run_forces_the_same_seed_as_the_first`); the image-side `replayed_cases`
  on a declaration with `source_pins` produces the digest the import sealed; a declaration
  whose pin names a repo the stand-in never fetches is fine (pins are looked up, not
  required to be used); the stand-in fetch with no pin on the declaration is refused at
  build with the F1 reason in the SKIPPED marker.
- [ ] **Steps 2–4 as above. Commit.**

### Task A5: The declaration's new fields and the gated skip (R6, R7, R8)

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (`TaskReplayCasesSpec` fields:
  `source_pins: dict[str, str] = field(default_factory=dict)`, `shuffle_seed`,
  `choice_shuffle_seed`, `excluded_sample_ids`, `needs_hf_token`),
  `src/screamingface_engine_inspect/benchmarks.py` (`_task_replay_pins` adds
  `source_pins=<sorted JSON>` when non-empty), `task_replay.py` (`prepare_replayed_cases`
  checks `needs_hf_token` before replaying, reusing the gated branch of `prepare_cases`)
- Test: `tests/unit/inspect/test_task_replay_assembly.py`, `test_task_replay.py` (append)

- [ ] **Step 1: Write the failing tests** — a declaration with `source_pins` has a fourth
  identity pin and a different revision from the same declaration without; an empty mapping
  adds no pin (the 16 URL-only rows); a gated declaration with no token and no skip flag
  raises by name; with the flag it writes SKIPPED with the gated reason and the summary has
  no `unconfirmed_cases` key (F7); `asdict` round-trips every new field through
  `spec.json`.
- [ ] **Steps 2–4. Commit.**

### Task A6: The named exclusion on Task replay (R9, D6)

**Files:**
- Modify: `src/screamingface_engine_inspect/capture.py` (`captured_case_records` drops the
  declaration's excluded ids through `_without_excluded_samples` before rendering) or
  `task_replay.py` and `import_replay.py` (the shared post-task step); choose the one place
  both children call: `captured_case_records`
- Test: `tests/unit/inspect/test_capture.py` (append)

- [ ] **Step 1: Write the failing tests** — two of four stand-in Samples are dropped by id,
  Cases renumber 1..2, the dropped ids never reach the digest; an id not present refuses by
  name.
- [ ] **Steps 2–4. Commit.**

### Task A7: No existing revision moves (Review Focus 9)

**Files:**
- Test: `tests/unit/inspect/test_published_revisions.py` (append a second parametrised
  test over every `TASK_REPLAY_CASES` key whose Case Sources are URL-only, asserting the
  revision literal captured on `main` `ec11a0608`; the Hub-fetching ones are left for D4)

- [ ] **Step 1: Write the test with the literals read from `main`. Step 2: it passes
  (nothing moved). Commit.**
- [ ] **Gates, wisdom review, ledger outcome, PR.** Title:
  `feat(screamingface-engine): enforce the declaration's Hub revision and seeds in Task replay (OME-1460)`.
  Body: `Refs: OME-1460`, the spec's Data Flow pointer, the Task 0 sweep output (both runs).

---

## PR B — the fold and the deletion (branch `one-fetch-path-fold`)

Spec R10, R12–R19, D1–D4, D6–D8. **After step 7 merges** (Global Constraints). Three
commits in this order: the 14 rows that need no forced seed, the 14 with forced seeds, the
deletion and the docs (P5). The reviewer reads the diff by commit.

### Task B1: Ledger, and the `--skip-append-only` ask

- [ ] Ledger as in A1; Owner-verify: "`--skip-append-only` for the 18 literal moves in
  `test_published_revisions.py` and the one in `test_inverted_grade.py`, and for the
  deletion of `test_inspect_cases.py` and the reader half of `test_inspect_importer.py`
  (tests of code that no longer exists); licence decisions for gsm8k, mmlu, winogrande,
  hellaswag, paws, race_h."

### Task B2: Re-import the 28 rows (two commits)

**Files:**
- Modify: `src/screamingface_engine_inspect/prepare.py` (28 rows out of `BENCHMARK_CASES`,
  28 into `TASK_REPLAY_CASES` with `source_pins`, the licence and the fold note (P4);
  `task_args` (`fewshot=0` ×2, `subset=` ×2), `needs_hf_token` ×2, `has_answer_key=False`
  ×2 on the unseeded half; `shuffle_seed=` on all of the seeded half, `choice_shuffle_seed=`
  on lab_bench ×6, `excluded_sample_ids=` and `task_args` on onet_m6,
  `keep_sample_metadata=True` on frontierscience (parent D11 decides it; assert it came out
  True)), `src/screamingface_engine_inspect/benchmarks.py` (the 28 `BenchmarkSpec` rows keep
  their key, title, description, scorer and judge; only the provenance comment changes),
  `src/screamingface_engine_inspect/pins.py` (the 28 rows' constants go)
- Test: `tests/unit/inspect/test_published_revisions.py` (18 literals move),
  `test_inverted_grade.py` (1 literal), `tests/unit/inspect/test_inspect_gsm8k_benchmark.py`,
  `test_inspect_mmlu_benchmark.py` and `test_inspect_frontierscience_benchmark.py`
  (re-pointed at the Task-replay declaration: the prepared-Case assertions stay, the
  `emit_cases` calls become `captured_case_records` on the stand-in Samples)

- [ ] **Commit 1, the unseeded half** (R12 rows 1, 2, 3, 7, 8: arc ×2, wmdp ×3, pubmedqa,
  gsm8k, winogrande, mmlu, aime ×2, hellaswag, xstest ×2). Step 1: run the importer, one row
  at a time, with the command the how-to shows and the task args above; keep the sweep's
  per-row line as the fold note. Step 2: write the failing test first for each re-pointed
  benchmark test, then the literal moves (each is RED until the row lands). Step 3: R13
  evidence, the sweep's id-set verdict for pubmedqa, xstest_safe (250) and xstest_unsafe
  (200), goes in the ledger. Lane green, commit.
- [ ] **Commit 2, the seeded half** (R12 rows 4, 5, 6: commonsense_qa, paws, boolq,
  mmlu_pro, race_h, frontierscience, onet_m6, musr, lab_bench ×6), the same steps; R13
  evidence for onet_m6 (kept ids equal today's, six excluded). Lane green, commit.

### Task B3: Backfill the Hub pins on the Task-replay rows that fetch unpinned (D4)

- [ ] Re-import medqa, bbq and piqa (and any other the sweep lists) with their Hub revision
  resolved; their digests must be unchanged (same content); their revisions move (a new
  literal each in A7's test, moved under the same ask). Part of commit 1.

### Task B4: lab_bench's answer stays shuffled (Review Focus 10)

- [ ] **Write the failing test first** in `tests/unit/inspect/test_inspect_task_replay_benchmarks.py`:
  for each lab_bench key, read the prepared Grading Material of a small prepared slice (the
  test fixture pattern that file already uses) and assert the target letters are not all one
  letter. Then land the rows. Part of commit 2.

### Task B5: The R15 lane first (RED before the deletion)

**Files:**
- Test: `tests/unit/inspect/test_inspect_imported_benchmarks.py` (append one parametrised
  test over every `TASK_REPLAY_CASES` key: assemble, grade one stand-in answer through the
  scorer adapter under `no_network`)

- [ ] **Step 1: Write it; it must pass on every key already** (nothing downloads in
  Grading). A key that fails names a scorer that reaches the network: STOP and ask.

### Task B6: Delete the Hugging Face path (R10, R17)

**Files:**
- Modify: `prepare.py` (R17's list), `benchmarks.py` (`_revision_pins`,
  `_dropped_question_pins`, the `BENCHMARK_CASES` import, `_cases_declaration` reads one
  registry), `importer.py` (the reader, `write_generated_rows`, `read_hub_dataset_facts`
  moves its Hub lookup to `task_replay_rows.py` where `card_license_of` already uses it, the
  four routes, `--task-replay`), `task_replay_rows.py` (writes `source_pins` and the seeds),
  `scorer_adapter.py` (its `CasesSpec` type reference)
- Delete: `pins.py`, `tests/unit/inspect/test_inspect_cases.py`
- Modify: `tests/unit/inspect/test_inspect_importer.py` (reader tests go; the Task-replay
  CLI tests stay and gain one: `test_main_imports_by_task_replay_without_a_flag`)

- [ ] **Step 1: Write the failing CLI test. Step 2: Delete. Step 3: Lane green;
  `check_layering.py` green; pyright green in an extra-less venv** (CI's pyright has no
  inspect extra). Commit 3 starts here.

### Task B7: Glossary and the architecture page (R18, R19)

**Files:**
- Modify: `CONTEXT.md` (the Task replay entry), `docs/importing-an-inspect-eval.md` (the
  sentences R19 lists, each flipped in place; no new section),
  `docs/adding-an-imported-benchmark.md` (one command, one declaration shape)

- [ ] **Step 1: Flip each R19 sentence; grep the page for "Hugging Face path", "OME-1460",
  "🔧", "⏳" and "28" afterwards and justify every survivor.** Part of commit 3.
- [ ] **Gates with `--skip-append-only` (owner-pressed), wisdom review, ledger outcome, PR.**
  Title: `feat(screamingface-engine): move the 28 Hugging Face-path Benchmarks to Task replay and delete the path (OME-1460)`.
  This PR closes the ticket: its ledger carries the close, the mirror
  `docs/tasks/2026-10-02-OME-1460-one-fetch-path.md` ships `status: done`.

---

## Owner presses (every one named here, none assumed)

| When | Press | Why |
| -- | -- | -- |
| before Task 0 | approve the spec (acceptance 9) | spec before plan before code |
| Task 0 | run the sweep on a machine with `HF_TOKEN` (or hand the agent one, read-only) | xstest ×2 are gated |
| PR B | `--skip-append-only` (18 + 1 literals, the deleted test files); licence decisions: gsm8k, mmlu, winogrande, hellaswag, paws, race_h | prior tests; the gate refuses `TODO` |
| after PR B merges | re-press the paid inspect smoke lane (`screamingface-paid-inspect-smoke.yml`) | its asset cache is keyed on the plugin source and it prepares every `inspect-*` bundle; the only paid lane that touches an Imported Benchmark. Not a golden: the ifeval e2e golden is a hand-built Engine Benchmark and does not move |
| D1–D8 | confirm or flip each before PR A (D1, D6, D8), before PR B (D2, D3, D4, D5, D7) | the spec's Decisions table |

No licence re-check is needed for the 22 rows whose `pins.py` note carries a cleared value:
the dataset and revision are the same, the value moves from a comment to `license=`.
