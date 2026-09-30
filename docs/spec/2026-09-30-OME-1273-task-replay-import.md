# Spec — import the Benchmarks whose Cases the importer can't see, by replaying the eval's own task

- Status: approved (owner, 2026-09-30). Design decisions: owner, 2026-09-30 (recorded on the ticket).
  Settled on this PR (owner, 2026-09-30): four refusals route to Task replay (R1), the strict
  image-job switch is approved (R11), the code ships as five PRs (Delivery), and the strict
  job's cost below is accepted.
- Component: `apps/screamingface-engine` (`screamingface_engine_inspect`).
- Ticket: [OME-1273](https://linear.app/openmined/issue/OME-1273/import-the-single-turn-benchmarks-the-importer-still-refuses). Parent epic: OME-1299.
- Ledger: `docs/work/2026-09-30-ome-1273-task-replay-spec.md`.
- Pinned to: `inspect-evals` 0.20.0, `inspect-ai` 0.3.263, main `42baa988`.

## TLDR

[inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0) is a library
of ready-made evals. Our **importer** copies one into ScreamingFace as an **Imported
Benchmark**. **Case Preparation** then fetches its Cases once at image build and freezes them
into the Engine's image. Think of the importer as a clerk who copies an eval's Cases. Today the clerk only
knows one filing cabinet, the Hugging Face Hub, and only when the eval opens that cabinet in
plain sight.

The rule: **we only serve Cases that someone reviewed, and they must be the same at every image
build.** The importer refuses 34 packages because it can't see where their Cases come from:

- the Hugging Face fetch sits in a helper file or goes through a loader script (medqa, bbq, bbeh)
- the Cases come from GitHub or another URL (agieval, mgsm)
- the Cases ship as a file inside `inspect_evals` (persistbench)
- several fetches happen and none is clearly the Cases, or a converter is written inside the task (chembench, DROP, pre_flight)
- an upstream bug at 0.20.0 gets in the way (bbh)

The change: we fetch the Cases the way Inspect does, by calling the eval's own task function.
Building its Task makes the eval load its dataset, which is the fetch we want. **This never runs
an evaluation:** no solver, scorer, model or Judge runs, and nothing is paid for. We record every
place the task fetched from (a **Case Source**) and fingerprint what it produced (the **Case
Digest**). Every image build calls the task function again and serves nothing if the fingerprint
differs.
**It never serves Cases nobody reviewed.** No existing Imported Benchmark changes. Up to 14
packages become Benchmarks here. The Judge-graded rest become fetchable, ready for the Judge
tickets.

## Before / After

<img src="../diagrams/2026-09-30-OME-1273-before-after.png" width="900">

Today a researcher whose paper reports on agieval or medqa finds no Benchmark, and nothing
visible says why. After this work, each of the 34 packages is either a Benchmark whose Cases are
proven unchanged at every image build, or carries a named reason it isn't one yet.

### Don't regress

- Existing Imported Benchmarks keep their code path and their Benchmark Revisions byte for byte.
  `tests/unit/inspect/test_published_revisions.py` pins all 17 literal revisions.
- Import review keeps its three parts: COPIED (transcribed from the eval), CAPTURED (observed at
  import), OURS (our own seeds and preparer revision).
- Refuse first. A shape we can't reproduce exactly is refused by name, never approximated: the
  placeholder guard (OME-1272) and the question filter (OME-1269) keep working unchanged.

## Architecture / Design

<a href="../diagrams/2026-09-30-OME-1273-architecture.png"><img src="../diagrams/2026-09-30-OME-1273-architecture.png" width="1000"></a>

Click the diagram for full size.

Files are relative to `apps/screamingface-engine/src/screamingface_engine_inspect/`.
`task_replay.py` is a proposed new module; the rest exist on main.

**What Task replay runs, and what it never runs.** Think of it as asking the eval to print its
question booklet, not to run the test.

| | What happens |
| -- | -- |
| **Runs** | The eval's `@task` function, called with its task args (`mgsm(languages=["en"])`). To build its `Task`, the function loads its dataset: mgsm downloads its TSV and checks upstream's sha256; agieval downloads a JSONL at a pinned GitHub commit. |
| **Taken** | `task.dataset` only: the Samples after the eval's own filtering and conversion. Our shared Case writer then renders each prompt and writes the Grading Material, as on the Hugging Face path. |
| **Never runs** | inspect's `eval()`. The solver (no `generate()`), the scorer, and every model and Judge. No API call is made and nothing is paid for. |

This is not new ground: the importer already calls task functions today, and so does the
question filter (OME-1269). Both swap `hf_dataset` for a stand-in; Task replay lets the real
fetch happen.

- **Choose the preparation path.** The Hugging Face reader runs first, because existing
  Benchmarks must keep their revisions. Only its four "can't see the fetch" refusals route
  onward (R1); every other refusal is a real mismatch, not blindness.
- **Task replay runs in a child process.** `inspect_evals` reads its cache directory once, when
  it is first imported (`INSPECT_EVALS_CACHE_PATH`). `inspect_ai.util.download` also skips a
  file whose cached copy matches. Only a fresh process with an empty cache fetches, and is
  recorded, every time.
- **The Case Source recorder wraps rather than stubs,** because the Case Digest needs the real
  Cases. It rebinds by identity (every module attribute that *is* the wrapped function), because
  evals import helpers by name: mgsm does `from inspect_ai.util import download`, so patching
  `inspect_ai.util` alone would miss it.
- **The Case Digest is taken twice at import.** An unseeded shuffle or generated Cases pass once
  and then fail at the next image build, so import catches it now.
- **The generated declaration splits review from enforcement.** Case Sources go in as comments
  (COPIED); the Case count and Case Digest go in as constants (CAPTURED). The reviewer judges
  *where* the Cases come from; the code enforces *what* they are.
- **Task-replay Case Preparation calls the eval's own loading code, not a copy of it,** because
  re-implementing each loader script by hand is exactly where silent mismatches come from. It
  shares prompt rendering and the writer with the Hugging Face path, so the two paths can't
  drift on how a Case is written.
- **A mismatch writes SKIPPED, not a crash,** so one changed URL can't take every other
  Benchmark in a deployed image dark. The PR image job runs strict, so the PR that caused a
  mismatch (usually a dependency bump) can't merge.

## Known limitations of this design

- **Image builds run Inspect's fetch code with network access.** A dead or moved URL takes that
  Benchmark dark (SKIPPED) until someone re-imports it. Accepted: it fails loudly, never with
  different Cases.
- **An upstream change fails every Engine PR's image job until it is fixed.** The strict job
  checks all Task-replay Benchmarks, not just the ones a PR touched, and the job has no build
  cache, so every run fetches every Case Source again. Accepted: the fix is one re-import, and a
  silent pass would let the drift reach a deployed image. Real drift should be rare: most of the
  14 fetch from a dataset revision, a commit or an upstream sha256, which can vanish but can't
  change. piqa's unpinned URLs are the known exception; the import's recorder lists any other. The likelier failure is a host
  that's briefly down. The Hugging Face path already carries that risk on every PR today, and
  Inspect's download helpers retry. If flakes show up, the fix is retrying the fetch, not
  loosening the check.
- **A fetch we don't wrap can't be imported.** An eval that downloads through plain `requests`
  or `urllib` produces Cases with no recorded Case Source, and is refused. It stays refused
  until upstream moves to an Inspect helper or we add its primitive to the recorder.
- **The Case Digest says *that* the Cases changed, not *what* changed.** Accepted: the fix is
  always a re-import and a fresh review, and that diff shows the difference.
- **Case Sources are review comments, not checked at build.** A source that moves but serves
  identical content passes. Accepted: what we serve is the Cases, and the digest pins those.
- **Only Task-replay Benchmarks get a Case Digest.** Hugging Face-prepared Benchmarks keep the
  Case count as their only drift guard. Backfilling a digest changes their Benchmark Revisions,
  so it needs its own ticket (not filed).
- **Two preparation paths live side by side.** Folding the Hugging Face path into Task replay
  is a later decision, not this ticket's.
- **Every count here is pinned to inspect_evals 0.20.0.** A version bump means re-running the
  sweep before trusting any number.

## Requirements

### Import side

- **R1. Routing.** The importer runs the Hugging Face reader first. Exactly these four refusals
  route to Task replay, as one distinct refusal kind; every other refusal stays a refusal:
  - the task module has no `hf_dataset` binding (`importer.py`:190 today);
  - the task never called `hf_dataset` (:508);
  - several `hf_dataset` calls, none of them the Task's dataset (:518);
  - `record_to_sample` is defined inside the task function (:491).

  Every existing import produces byte-identical generated code.
- **R2. Task replay.** It calls the eval's task function with the declared task args, and only
  that: it never calls inspect's `eval()`, so no solver, scorer or model runs. The call happens
  in a child process whose `INSPECT_EVALS_CACHE_DIR` and Hugging Face cache point at a fresh, empty
  directory. The Samples are the Task's dataset after the task's own filtering, shuffling and
  conversion, as inspect would run them.
- **R3. Case Source recorder.** A pass-through wrap on each fetch primitive below records one
  Case Source per call: its kind (Hugging Face, URL, file inside the package), its location, and
  its pin (dataset revision, a commit in the URL, or an upstream sha256), or "unpinned".

  | Primitive | Seen in |
  | -- | -- |
  | `datasets.load_dataset` | `hf_dataset`, inspect_evals' Hugging Face wrappers |
  | `huggingface_hub.snapshot_download`, `hf_hub_download` | loader-script datasets (medqa, bbq) |
  | `inspect_ai.util.download` (URL + sha256) | mgsm |
  | `inspect_evals.utils.load_dataset._download_remote` | `load_json_dataset`, `load_csv_dataset` (agieval) |
  | `inspect_ai._util.file.file` | `json_dataset`, `csv_dataset`, `file_dataset` reading a path (persistbench) |

  The wrap rebinds every loaded module attribute that is the same function object.
- **R4. Import refusals, each by name.** The task raises; it yields no Samples; it yields
  Samples but no Case Source was recorded; two Samples share an id; the two runs' Case Digests
  differ. The existing solver and scorer refusals (templates, system messages, scorer count)
  still apply.
- **R5. Case Digest.** The sha256 of the canonical JSON (sorted keys, no whitespace, UTF-8) of
  the ordered list of prepared Cases, each exactly as the writer writes it: id, rendered input,
  and Grading Material (target, choices, and metadata when kept). It is computed from the same
  code that writes the files, never from a second serialisation.
- **R6. Generated declaration.** A Task-replay Imported Benchmark gets its own declaration
  type, not new optional fields on `CasesSpec`, because none of `CasesSpec`'s dataset-pin fields
  apply. It carries the task reference and args, the prompt facts the importer already reads,
  the Case count, the Case Digest, and a licence field. The importer writes each Case Source
  above it as a comment, and the licence as `TODO`. Where upstream supplied no hash, the comment
  says the Case Digest is the only pin.
- **R7. Licence gate.** A test refuses any Task-replay declaration whose licence is still `TODO`,
  next to the existing test that refuses unfinished catalogue prose
  (`test_inspect_imported_benchmarks.py`). The owner decides each licence; a Case Source with no
  Hugging Face dataset card has no licence the importer can read.
- **R8. Scorer lookup in helper files.** Scorer lookup searches the eval package's loaded
  modules, as template lookup already does (`_template_attribute`), and accepts a match only if
  it is the same object the Task holds. bbeh and livebench need this.

### Image side

- **R9. Task-replay Case Preparation.** It calls the task function again in a child process (R2), renders
  prompts with the same code as the Hugging Face path, then checks the Case count and the Case
  Digest before writing anything.
- **R10. Mismatch.** A different Case Digest, a different count, or a failed fetch writes the
  existing `SKIPPED` marker with a reason naming the Benchmark and the expected and actual
  values, writes no Cases, and moves on to the next Benchmark. At run time the Benchmark answers
  with the existing benchmark-unavailable error, carrying that reason.
- **R11. Strict image job.** With `SCREAMINGFACE_FAIL_ON_CHANGED_CASES=1`, Case Preparation
  still writes every marker, then exits non-zero and lists every Benchmark it skipped for R10.
  Only the PR image job (`screamingface-engine-tests.yml`, job `image`) sets it (owner-approved,
  2026-09-30).
- **R12. Benchmark Revision.** The task reference, its args and the Case Digest join a
  Benchmark's revision pins only on a Task-replay Benchmark. All 17 published revisions stay
  byte-identical.

### Benchmarks and glossary

- **R13. The 14 Benchmarks.** Each is imported with its Case Digest agreeing across two Case
  Preparations and its owner licence decision in the diff. agieval, medqa and mgsm come first
  because papers cite them most.

  | Package | Case Source kind | Grading | Scope note |
  | -- | -- | -- | -- |
  | agieval | GitHub URL at a commit, no upstream hash | choice | not its math task (Judge-graded) |
  | medqa | Hugging Face + loader script | choice | — |
  | mgsm | URL + upstream sha256 | numeric match | — |
  | bbq | Hugging Face + loader script | choice | — |
  | piqa | Hugging Face; loader script fetches unpinned URLs | choice | the Case Digest is its only pin |
  | bbeh | Hugging Face, from a helper file | own scorer in a helper file | needs R8 |
  | cybermetric | GitHub commit + sha256 | choice | 4 tasks |
  | worldsense | GitHub commit + sha256 | pattern match | — |
  | sad | GitHub commit + sha256 | lenient multiple choice | 5 tasks |
  | livebench | Hugging Face, helper file, one revision per category | own scorer | needs R8 + its git dependency in the image |
  | sevenllm | Hugging Face file URL at a commit | choice | multiple-choice tasks only |
  | cyberseceval_4 | GitHub commit, some with sha256 | per task | deterministically graded tasks only |
  | pre_flight | Hugging Face; Case fields declared inline | choice | — |
  | chembench | Hugging Face, 9 fetches | own scorer | — |

  The other 20 packages' destinations (Judge tickets, OME-1419, OME-1268, OME-1271, upstream
  issues) live in OME-1273's table. Here they only need to become fetchable, or to carry a named
  reason.
- **R14. Upstream issues.** We draft the four upstream issues (bbh, personality, sciknoweval,
  novelty_bench); the owner posts them.
- **R15. Glossary.** `CONTEXT.md` gains **Case Source** and **Case Digest**, and Case
  Preparation now reads "from its pinned Case Sources" instead of "at a pinned dataset revision".

## Out of scope

- A Case Digest for Hugging Face-prepared Benchmarks: it changes their revisions (see Known
  limitations).
- Judge-graded packages: they become fetchable here and are imported by OME-1370, OME-1371 and
  OME-1400.
- DROP's worked examples (OME-1419), stereoset's two scorers (OME-1268), mind2web's images
  (OME-1271), bold's torch classifiers (no ticket).
- Named Deviations on Task-replay Benchmarks (excluded ids and the like). None of the 14 needs
  one; add it when a Benchmark does.
- Checking Case Sources at build (see Known limitations).

## Delivery — stacked PRs, each under about 500 lines

1. This spec and the glossary entries. Docs only.
2. Image side: the declaration type, Task-replay Case Preparation, the Case Digest check, SKIPPED
   and the strict switch with its one CI line, the revision pins (R5, R9-R12). Tested with a hand-written declaration.
3. Import side: routing, the recorder, the double run, the generated declaration and the licence
   gate (R1-R7).
4. Scorer lookup in helper files (R8), split out so PR 3 stays under the cap.
5. agieval, medqa, mgsm.
6. The other 11, plus the four upstream issue drafts (R14).

A plan in `docs/plan/` follows this spec's approval and fixes each PR's file list and tests.

## Acceptance

1. All 34 packages end in exactly one destination from OME-1273's table. Every imported one has
   its Case Digest verified by two Case Preparations and its owner licence decision in the diff.
2. `test_published_benchmark_revision_is_byte_identical` passes unchanged: no existing Imported
   Benchmark's Benchmark Revision moves.
3. A test pins that a Case Digest mismatch writes SKIPPED with the reason and serves nothing, and
   another pins that the strict switch turns it into a non-zero exit.
4. A test pins that each of the four R1 refusals routes to Task replay and every other refusal
   does not.
5. The owner approves this spec before the first line of code (approved 2026-09-30).
