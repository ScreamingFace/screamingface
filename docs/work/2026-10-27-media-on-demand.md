---
ticket: OME-1271
stack: screamingface-engine
status: done
started: 2026-10-27
finished: 2026-10-27
---

# media-on-demand — park each Case's pictures and files at finish, so a researcher can open one

## Intent

PR 5 of OME-1271. Since #1558 a Case Result shows each picture or file as a placeholder (type,
size, sha256), so a researcher has no way to see the picture the model saw. The client-facing
engine process can't read the Benchmark files (they ship only in the Runner image), but it
already serves the result store at `GET /artifacts/{id}`, and that store names every item by the
sha256 of its bytes: the same value the placeholder carries. So when a run finishes, the Runner
parks each distinct picture and file in that store; the SDK fetches one by its placeholder's
sha256 and checks the bytes, and the report browser puts its button on its placeholder line in
the Case card. Items expire with the
store's own rule: 48 hours on the filesystem store (`artifact_ttl_s`, restarted each time a run
parks the same bytes again). On S3 that is a bucket lifecycle rule, which no deployment configures
today, so a deployment keeps every parked picture until someone deletes it.
Design agreed with the owner on 2026-10-27.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/media_parking.py` (new): the
  run-scoped parker (read the Case, decode each picture or file, write it once per run) and its
  binding.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/candidate_input.py`: one helper,
  `media_bytes`, so parking and `media_placeholder` decode a part the same way.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/aggregation.py`:
  `finalize_candidate_result` parks each Case's media before the echo.
- `apps/screamingface-engine/src/screamingface_engine/runner/operation_capture.py` and
  `runner/main.py`: bind the parker for each run, with the run's result store.
- Tests: `tests/unit/test_media_parking.py` (new).
- SDK (`packages/screamingface`): `media.py` (new: `CaseMedia`, `FetchedMedia`, `case_media`),
  `_engine/media.py` (new: the checked fetch), `_ui/media_panel.py` (new: Show picture / Save
  file, in place in the Case card), `CaseResult.media`, `Client.fetch_media`, `sf.fetch_media`, `MediaUnavailableError`,
  the report browser hook, the surface snapshot and the changelog; `tests/test_case_media.py`.

## Test plan

- A picture Case parks the decoded bytes, named by their sha256, equal to the placeholder's.
- The same picture in two Cases, or for two Candidates of one run, is written once.
- A text Case, a refused Case, and an unbound run park nothing.
- A store that fails to write is logged and the run's result is unaffected.
- Through `finalize_candidate_result`: the parked id equals the echoed placeholder's sha256.
- The run wrapper binds the parker with the run's store for every step.
- The App's reader serves a parked picture's bytes by that sha256.
- SDK: a Case lists its pictures and files from the engine's echo (and from an older inline
  `data:` URI); a fetch returns the bytes only when size and sha256 match; 404 is
  `media_not_kept`; a malformed sha256 is refused before any request; a picture shows inline and
  a file saves under its own name; in the browser each placeholder line gets its button, a
  picture is fetched only on its click and drawn in place, and a failed fetch shows the reason.

## Acceptance

- After a picture run, `GET /artifacts/<placeholder sha256>` returns that picture's bytes.
- Text-only runs write nothing extra to the store.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except `candidate_input.py` is unchanged: the parker decodes on
  its own, because a shared helper would have pushed that file past 450 lines; a test pins that
  the parked name equals the echoed placeholder's sha256.
- **Commits:** engine — feat(screamingface-engine): park each Case's pictures and files in the
  result store at finish; SDK — feat(screamingface): open a Case's pictures and files from its
  Case Result.
- **Gates:** relevant tests only. Engine: `test_media_parking.py` (11) plus the 12 files around
  the finalizer and the run wrapper, 178 passed; the wiring tests fail when either wiring point
  is removed. SDK (`--extra notebook`): `test_case_media.py` (15) plus the browser, navigation,
  Colab, pagination, placeholder-conformance and public-surface tests, all green; the browser
  test fails without its hook. ruff, ruff format, pyright clean on touched files; layering OK.
- **Deviations:** the Python entry point is `sf.fetch_media(item)` / `Client.fetch_media(item)`,
  not `report.fetch_media`: a fetch needs only the sha256, so the Report adds nothing.
  `report_browser.py` is 452 lines (was 445).
- **After the owner's local run (2026-10-27):** FigQA and TableQA ran end to end on the local stack
  (3 Cases each, a single model and a two-member Fusion): every Case scored, no `base64,` in any
  result, and all 8 pictures parked under their placeholder's sha256. Clicking Show picture
  worked (two `GET /artifacts/<sha256>` 200s in the engine log). The owner asked for the button
  on the picture's own line instead of a row under the Case, so `media_panel.py` now marks each
  placeholder line in the card and draws the picture in place; a picture whose line the card's
  10,000-character clip cuts off gets its button at the top of the question. That rewrite found
  a bug: Save file wrote the file as the browser's not-yet-created folder; it now writes to the
  full path. Gates: the six browser, media, navigation, Colab and pagination test files, 77
  passed; ruff, ruff format, pyright clean. Owner check left: the dev notebook run.
- **After review (2026-10-28):** parking now runs in a worker thread at the two async places a
  Candidate's result is finished (`benchmark_aggregation.py`, `incremental.py`), not inside the
  finalizer on the run's event loop: the writer is synchronous, and a slow store froze the loop. A
  store that fails once is not tried again in that run, so a store that is down costs one timeout,
  not one per picture per Candidate. The expiry wording now says what is true: no deployment
  configures a bucket expiry rule today, so a deployment keeps parked pictures (ops follow-up).
  SDK: the browser keeps at most 20 opened pictures drawn (each held as base64 in the kernel), a
  file name the system can't write shows a notice instead of a traceback, and `_engine/media.py`
  shares the sha256 pattern with `case_result.py`. Each new test fails when its fix is removed.
  Gates: engine, `test_media_parking.py` plus the aggregation, early-grading and echo tests, 118
  passed; SDK, the media, browser, navigation, Colab, pagination and public-surface tests, 119
  passed; ruff, ruff format, pyright clean on touched files.
