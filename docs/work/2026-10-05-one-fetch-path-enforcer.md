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

(filled after the sweep runs)

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
