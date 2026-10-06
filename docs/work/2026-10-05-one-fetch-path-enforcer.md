---
ticket: OME-1460
stack: screamingface-engine
status: done
started: 2026-10-05
finished: 2026-10-05
---

# one-fetch-path-enforcer — Task replay forces the declaration's Hub revision and seeds

## Intent

PR A of OME-1460 (spec `docs/spec/2026-10-02-ome-1460-one-fetch-path.md`, plan
`docs/plan/2026-10-02-OME-1460-one-fetch-path.md`). Before the 28 Hugging Face-path
Benchmarks can move to Task replay (PR B), Task replay must be able to pin what they fetch:
the Case Source recorder grows a fetch-pin enforcer that forces the declaration's Hub
revision onto every Hub fetch the eval makes and the declaration's seeds onto a shuffle the
eval makes without one, in the import child and the image-side child alike. The declaration
gains the fields that carry those pins, the gated-dataset skip reaches Task replay, and the
importer writes the pins into the generated row. Spec R1–R8, D1, D7 (function level), D8
(fields only).

## Planned changes

- Create `apps/screamingface-engine/src/screamingface_engine_inspect/fetch_pins.py`:
  `FetchPins` (source pins, or None while the import's first run learns them; the two
  seeds), `FetchPinError`, and the pure forcing rules (revision; `hf_dataset` arguments).
- Modify `case_sources.py`: `CaseSourceRecorder.install(pins=None)`; Hub primitives carry
  their repo argument; the depth-1 wrap forces the revision and remembers each Hub repo's
  revision; a non-recording wrap on `inspect_ai.dataset.hf_dataset` forces revision and
  seeds.
- Modify `prepare.py`: `TaskReplayCasesSpec` gains `source_pins`, `shuffle_seed`,
  `choice_shuffle_seed`, `needs_hf_token`; the gated check is shared by both paths.
- Modify `benchmarks.py`: `_task_replay_pins` adds `source_pins=` when non-empty.
- Modify `task_replay.py`: the image-side child installs the enforcer from the
  declaration; `prepare_replayed_cases` honours `needs_hf_token`.
- Modify `import_replay.py`: run 1 forces the seeds and learns the Hub revisions; the
  importer resolves each to a commit (and reads the gate) and seals `source_pins`; run 2
  enforces them.
- Modify `task_replay_rows.py`: the generated row writes `source_pins`, the seeds and
  `needs_hf_token`.
- Modify `prepare.py` rows medqa, bbq, piqa: `source_pins` from their recorded pin (D4).
- Create `apps/screamingface-engine/scripts/sweep_task_replay_fold.py` (Task 0, P1).
- Tests (append only): `test_fetch_pins.py` (new), `test_case_sources.py`,
  `test_import_replay.py`, `test_task_replay.py`, `test_task_replay_assembly.py`,
  `test_task_replay_rows.py`, `test_published_revisions.py`.

## Test plan

- Revision (R2, F1, F2): a missing revision is replaced by the pin before `load_dataset`
  runs; a branch name is replaced; a different sha is refused naming both; a repo with no
  pin is refused naming it; `snapshot_download` and `hf_hub_download` follow the same rule;
  with no pins installed nothing is forced (today's behaviour).
- Rebind (R1): `hf_dataset` imported by name before install, and the inspect_evals shim,
  both reach the enforcer.
- Seeds (R3, F6): `shuffle=True` with no seed gets `shuffle_seed`; `shuffle_choices=True`
  becomes the int `choice_shuffle_seed`; a seeded call and `shuffle_choices=False` are
  untouched; `shuffle=False` never gains a seed; an unseeded shuffle with no declared seed
  is refused by name.
- Both children (R4, R5): with a stand-in eval that loads from a fake Hub, an unseeded
  shuffle seals under `shuffle_seed` and both runs agree; the image-side child fetches at
  the pinned revision; a Hub fetch with no pin is SKIPPED at build with the F1 reason.
- Declaration (R6, R7): `source_pins` adds a fourth identity pin; an empty mapping adds
  none; the new fields round-trip through `spec.json`.
- Gated (R8, F7): no token and no skip flag refuses by name; the skip flag writes SKIPPED
  with no `unconfirmed_cases` key.
- Writer: the generated row carries `source_pins`, seeds and `needs_hf_token`, and still
  parses.
- Review Focus 9: every URL-only Task-replay row keeps its revision byte for byte.

## Acceptance

- Spec acceptance 4 (revision: refused, replaced, pinned by a test each).
- Spec acceptance 6, first half (a seedless shuffle gets the declaration's seed and the two
  replays agree; no seed on the declaration refuses by name).
- Spec acceptance 7, second half (a gated declaration's PR build skips with the gated reason
  and no `unconfirmed_cases` key).
- No URL-only Task-replay Benchmark's revision moves; only the three D4 rows move.
- `run_gates.py screamingface-engine` green.

## Task 0 sweep

Ran `scripts/sweep_task_replay_fold.py` on this branch (enforcer installed), 2026-10-05/06,
against the live sources, with a cached Hugging Face login. `main` has **30** Hugging
Face-path rows, not the spec's 28: coconot's two rows came with OME-1371.

- **All 30 import** under Task replay with the row's seeds. Five first failed on Hub or CDN
  network errors (mmlu, mmlu_pro, wmdp_cyber) or on the gated fetch (xstest ×2); all
  passed on retry, xstest after the cached-login fix in this PR.
- **Every one of the 30 evals already passes a 40-hex commit** to the Hub, so no fold row
  needs a resolved pin (D4's list from the fold is empty).
- **10 identical, 9 order only, 10 differ in text, and mmlu is a subset.** The text changes the spec predicted
  hold: musr and xstest ×2 gain the system message (D3); lab_bench ×6 differ in their
  answer options (D1).
- **Three results the spec did not predict, each explained; PR 2 amends the spec's R12 table:**
  - mmlu serves 105 fewer Cases (14,042 → 13,937): inspect's own `get_mmlu_dataset` runs
    `filter_duplicate_ids` over content-hash Sample ids, so Task replay sends exactly what
    inspect sends and today's row serves 105 duplicate questions.
  - every hellaswag Case differs, first by a leading newline: the eval's `SYSTEM_MESSAGE`
    itself starts with one; capture keeps it, today's row strips it (`.strip()`).
  - frontierscience's "ids differ" is a sweep artifact: the eval numbers repeated ids with a
    process-wide counter, and the sweep built today's Samples twice in one process; every
    replay child is fresh, so builds are unaffected.

| Key | Import | Cases | Text | Hub commit | Note |
| -- | -- | -- | -- | -- | -- |
| aime24 | ✅ | 30 → 30 | order only | 8d88b2876a82 |  |
| aime25 | ✅ | 30 → 30 | order only | 563bb8404243 |  |
| arc_challenge | ✅ | 1172 → 1172 | identical | 210d026faf99 |  |
| arc_easy | ✅ | 2376 → 2376 | identical | 210d026faf99 |  |
| boolq | ✅ | 3270 → 3270 | order only | 35b264d03638 |  |
| coconot_contrast | ✅ | 379 → 379 | identical | 2cbe16aabf90 |  |
| coconot_original | ✅ | 1001 → 1001 | identical | 2cbe16aabf90 |  |
| commonsense_qa | ✅ | 1221 → 1221 | order only | 94630fe30dad |  |
| frontierscience | ✅ | 160 → 160 | order only | 25ed67db7da8 | ids differ only in the sweep: the eval numbers repeated ids with a process-wide counter and the sweep ran it twice in one process |
| gsm8k | ✅ | 1319 → 1319 | identical | cc7b047b6e5b |  |
| hellaswag | ✅ | 10042 → 10042 | 10042 Cases differ | 218ec52e09a7 | all Cases differ; first difference is the leading newline the eval's own system message starts with (capture keeps it, today's row strips it) |
| lab_bench_cloning_scenarios | ✅ | 33 → 33 | 33 Cases differ | 5c77cec64843 | differs in the answer options, expected from the forced choice seed (D1); PR 2 confirms order is the only change |
| lab_bench_dbqa | ✅ | 520 → 520 | 513 Cases differ | 5c77cec64843 | as above (D1) |
| lab_bench_litqa | ✅ | 199 → 199 | 192 Cases differ | 5c77cec64843 | as above (D1) |
| lab_bench_protocolqa | ✅ | 108 → 108 | 107 Cases differ | 5c77cec64843 | as above (D1) |
| lab_bench_seqqa | ✅ | 600 → 600 | 589 Cases differ | 5c77cec64843 | as above (D1) |
| lab_bench_suppqa | ✅ | 82 → 82 | 79 Cases differ | 5c77cec64843 | as above (D1) |
| mmlu | ✅ | 14042 → 13937 | a subset of today's | c30699e8356d | 105 fewer Cases: inspect's own duplicate filter drops 105 repeated questions today's row serves |
| mmlu_pro | ✅ | 12032 → 12032 | order only | 527feea0afed |  |
| musr | ✅ | 250 → 250 | 250 Cases differ | 7c365b439a22 | gains the eval's system message (D3) |
| onet_m6 | ✅ | 391 → 391 | order only | 93ffb5e3f3ec | the +6 ids are the six named exclusions (the sweep lists ids before exclusion); same 391 Cases |
| paws | ✅ | 8000 → 8000 | order only | 161ece9501cf |  |
| pubmedqa | ✅ | 500 → 500 | identical | 9001f2853fb8 |  |
| race_h | ✅ | 3498 → 3498 | order only | 2fec9fd81f1d |  |
| winogrande | ✅ | 1267 → 1267 | identical | 01e74176c635 |  |
| wmdp_bio | ✅ | 1273 → 1273 | identical | 7125571f22f0 |  |
| wmdp_chem | ✅ | 408 → 408 | identical | 7125571f22f0 |  |
| wmdp_cyber | ✅ | 1987 → 1987 | identical | 7125571f22f0 |  |
| xstest_safe | ✅ | 250 → 250 | 250 Cases differ | f1d713187c61 | gains the eval's system message `You are a helpful assistant.` (D3); kept ids equal (R13) |
| xstest_unsafe | ✅ | 200 → 200 | 200 Cases differ | f1d713187c61 | gains the eval's system message `You are a helpful assistant.` (D3); kept ids equal (R13) |

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1460.json` (the
  owner's blob-pinned approval of the one prior-test change) and pre_flight and bbeh pinned
  in `prepare.py` (imported by #1225 after this branch was cut). Source +546/-57, tests
  +902/-1.
- **Commits:** the enforcer (`case_sources.py`, `fetch_pins.py`); the declaration fields,
  both children and the gated skip; the row writer; medqa, bbq, piqa pinned with the 22-row
  revision freeze; the sweep script; the narrowed prior test and its approval; pre_flight
  and bbeh pinned. Branch `OME-1460-one-fetch-path-enforcer`, rebased on `4adfca73a`.
- **Gates:** `run_gates.py screamingface-engine --base <merge base>` ALL GATES GREEN (append-
  only check accepts the OME-1460 approval; 5,5xx tests; coverage 93.9%). All 27 Task-replay
  Benchmarks on main prepared against their live sources under the enforcer, every one OK
  with its sealed digest.
- **Deviations:**
  - D4 moved from PR B into this PR, and widened to five rows (medqa, bbq, piqa, pre_flight,
    bbeh): the enforcing build refuses a Hub read with no declared pin (F1), so without
    their pins they would go SKIPPED the day this merges. Each eval already passes the same
    commit; digests are unchanged; only their revisions move.
  - The row writer (`task_replay_rows.py`) writes the pins, seeds and gate here, not in
    PR B: a row imported between the two PRs would otherwise be refused at its first build.
  - The rules live in a new `fetch_pins.py`, not inside `case_sources.py` (plan P2): the
    450-line file cap; the import-time commit resolver (`source_pins_of`) sits beside them.
  - Only inspect's real `hf_dataset` is wrapped, not also the inspect_evals shim (R1): the
    shim calls it through the module attribute the wrap rebinds; a test drives both routes.
  - Task A6 (named exclusion on Task replay) was already on main (#1222); nothing to do.
  - The sweep ran once, after the enforcer (no run on bare main: it needs the seed
    parameters), over 30 rows, not 28: coconot's two rows were added by OME-1371.
  - One prior test narrowed with the owner's approval (the three-pin check skips rows that
    declare `source_pins`); the new 22-row freeze carries its invariant exactly.
  - The importer CLI's seed flags under Task replay (D7) stay with R10 in PR B.
  - Bug found by the sweep and fixed here (R8): the replay child moved XDG_CACHE_HOME, so
    huggingface_hub looked for a cached login token in the child's empty cache and xstest
    failed for a dev without HF_TOKEN exported. The child now keeps the builder's
    HF_TOKEN_PATH; CI (which exports HF_TOKEN) was never affected.
