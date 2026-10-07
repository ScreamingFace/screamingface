---
ticket: OME-1492   # filed before work start (owner-authored); this is PR 3 of 3
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-07
finished: 2026-10-07
---

# hand-built-provenance — every hand-built bundle says where its Cases came from

## Intent

OME-1492 PR 3. PR 1 gave every Imported Benchmark's bundle a `provenance.json` (where its Cases
came from: the dataset commit, any forced seed, Samples yielded / excluded / kept, seconds) and a
"Where the Cases came from" table on the paid smoke's run page. The six hand-built preparers
(draco, ifeval, healthbench, gdpval, medxpert, contracteval) still write none, so their rows read
"not recorded". This unit gives each of them the same block, written before `cases.json`, and
maps the four Benchmarks that share a bundle (draco-3pass, both HealthBench Benchmarks,
gdpval-text) to that bundle on the run page. No Benchmark Revision moves, never any Case text.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/bundle_provenance.py` (new, core):
  `PROVENANCE_FILE`, `PROVENANCE_KEY`, `write_provenance`, `read_provenance`, the Hugging Face
  source shape, and the hand-built block builder.
- `.../screamingface_engine_inspect/replay_provenance.py`: import the file name, key and writer
  from core (same public names).
- The six `benchmarks/<benchmark>/prepare.py`: write the block right before `cases.json`; the
  public `prepare` adds it to the summary.
- `packages/screamingface/tests/paid/_case_provenance.py`: the Benchmark-to-bundle map; an
  empty `pins` renders "—".

## Test plan

- One appended test per preparer's test file: `provenance.json` exists and was written before
  `cases.json`; the source pin is the declared revision; `samples.kept` = Cases written; the
  summary carries the same block; no fixture Case text in the file.
- SDK: a shared-bundle Benchmark reads its bundle's file; a hand-built block with empty `pins`
  renders.

## Acceptance

- Each of the six hand-built bundles holds `provenance.json` after Case Preparation, and the
  summary line carries it.
- The run page shows a row for every Benchmark, hand-built ones included.
- `run_gates.py screamingface-engine` and `run_gates.py screamingface` green; layering check green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/screamingface-engine/tests/unit/_bundle_provenance_checks.py`
  (the checks the six appended preparer tests share) and the spec
  `docs/spec/2026-10-07-OME-1492-pr3-hand-built-provenance.md` (per-preparer table).
- **Commits:** the feature commit (record where each hand-built bundle's Cases came from), the
  docs commit (spec, ledger, mirror line), the approval commit (pins the SDK helper edit in
  `.claude/test-change-approvals/OME-1492.json`), and one review-fix commit.
- **Gates:** `run_gates.py screamingface-engine --base <merge-base with main>` and
  `run_gates.py screamingface --base <merge-base with main>` ALL GREEN, no skip flag; the
  approvals file carries the SDK helper's blob against main (regenerated after each rebase). Free paid-lane tests: `SCREAMINGFACE_TEST_PAID=1 uv run pytest tests/paid -m "not paid"` green.
- **Deviations:**
  - `excluded` stays `yielded − kept` (PR 1's rule), so gdpval reads 220 / 118 / 102, not the
    summary's 7 unreadable tasks; the summary keeps `excluded_tasks: 7` unchanged.
  - ifeval lists a second source, the vendored official file at the verifier commit, because its
    text wins on key 2785. ifeval's nltk data is left out: it feeds the verifier, never a Case.
  - Review fixes (2026-10-07): the ifeval file's location gains its missing
    `instruction_following_eval/` folder (GitHub returns 404 for the shorter path), and the test
    now derives it from the vendored files' upstream banner instead of copying the string;
    gdpval lists its reference files as one `unpinned` url source (58 files behind 36 of the 102
    Cases on the current pins), so the label no longer reads fully pinned; the Case Source words
    (`url`, `unpinned` included) now live only in core, and the plugin imports them; the plan
    `docs/plan/2026-10-07-OME-1492-pr3-hand-built-provenance.md` is committed (recorded at review
    time) and the approvals reason points at it.
  - #1268 and #1284 merged before their review fixes were pushed, so this PR carries both fix
    commits (rebased onto main): the used-folder refusal and NaN-time row from #1268's review,
    the repeated-Case test and docs from #1284's. Their ledgers record them. The OME-1492 mirror
    closes here, since this is the last PR of the ticket.
  - Not done: a check that the SDK's shared-bundle map matches the Engine's registrations. It
    would make an Engine test read an SDK test helper by path; today all four entries are right,
    and a new shared bundle shows as a visible "not recorded" row on the press page.
  - Each preparer writes the block where it writes `cases.json` (the only place the kept count
    exists), and its public `prepare` reads the block back into the summary, so `emit`/`build`
    keep their return shapes and no existing test changed.
- **Owner-verify:** the next image build's summary lines for the six hand-built bundles carry
  `provenance`, and the next paid press's "Where the Cases came from" shows a row with a source
  for every Benchmark, the four shared-bundle ones included.
