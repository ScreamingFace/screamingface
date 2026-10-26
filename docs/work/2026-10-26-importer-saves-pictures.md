---
ticket: OME-1271
stack: screamingface-engine
status: done
started: 2026-10-26
finished: 2026-10-26
---

# importer-saves-pictures — the importer saves an eval's pictures inside the Case

## Intent

The importer builds every Case by Task replay: the eval's own solver chain runs on each Sample,
and the messages it hands the model at its first `generate` become the Case. Today it refuses
any Sample whose messages carry a picture ("a Case is text only"), so LAB-Bench FigQA and
TableQA, MMMU and MathVista cannot be imported. This unit writes such a Case as the v2
candidate-input envelope, with each picture inline as a `data:` URI, inside the per-Case size
limits. Every run after that serves the picture in place, with no fetch. Text-only Cases keep
their exact bytes, so no existing Benchmark changes. It is OME-1271's PR 2, and it may not merge
before OME-1679 (#1552), so that no picture Case is imported before the Fusion synthesizer can
see pictures.

Owner decisions this unit follows (2026-10-26, on OME-1271 and in this session):

- A picture's media type comes from its bytes: the four allowed signatures (PNG, JPEG, GIF,
  WebP) are read from the decoded bytes, and the `data:` label is rewritten to match. Bytes that
  are none of the four are refused.
- Sources: a `data:` URI, or a local file the eval wrote into the replay's own cache. An
  `http(s)://` picture, or any other scheme, is refused by name, so building a Case never fetches.
- `detail`: inspect's default `auto` is left out of the envelope; `low` and `high` are kept;
  `original` is refused by name.
- Shape: pictures only, in the one-prompt shape (leading system text, then one user message).
  The system text becomes the user message's first text part, the same fold text Cases use.
  Refused by name: a PDF, audio or video part, a picture inside a multi-turn conversation, and
  a picture in a system message.
- No "needs pictures" field on the Benchmark: a picture Case is exactly a v2 envelope, so
  OME-1548 can read that from the Cases.
- A Case over the limits fails the import, naming the Case; no Case is dropped.

Already true on main, so no change here: every import uses a fresh `INSPECT_EVALS_CACHE_DIR`
under a new temporary folder (`replay_environment`, `task_replay.py`), and capture records the
messages after the solver chain has run (`_StandIn`, `capture.py`), so text inspect moves after
the pictures stays where inspect put it.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/picture_input.py` — new: the
  per-Case limits, the bytes sniff, the source read, and the one-prompt picture Case writer.
- `apps/screamingface-engine/src/screamingface_engine_inspect/conversation_input.py` — the v2
  writer beside the v1 one, both with the same bytes style.
- `apps/screamingface-engine/src/screamingface_engine_inspect/capture.py` — `_input_text`
  hands a message list with a picture to the new writer instead of refusing it.
- `apps/screamingface-engine/tests/unit/inspect/test_picture_cases.py` — new (inspect extra).
- `apps/screamingface-engine/tests/unit/test_picture_case_limits_fit_the_gateway.py` — new
  (extra-less): the largest Case plus request overhead fits under the gateway's body cap.

## Test plan

- FigQA's shape (picture then question, `multiple_choice`) captures as a v2 envelope: the
  picture first, inspect's rendered text after it, and the shared parser reads it back.
- A picture labelled `image/jpeg` whose bytes are a PNG is written as `image/png`; bytes that
  are no allowed picture are refused by name.
- A picture read from a local file under the replay cache; a file outside it, and an
  `https://` picture, are refused.
- `detail`: `auto` left out, `high` kept, `original` refused.
- Limits: a Case over 8 MB and a 21st picture are each refused, naming the Case; one big
  picture inside the Case limit is saved (TableQA's 5.21 MB picture).
- Refused shapes: a picture in a system message, a picture inside a conversation, an audio part.
- Leading system text becomes the first text part.
- A text-only Case keeps its exact bytes (the existing capture tests stay green, unchanged).
- The Case Digest of a picture Case is the same on a second capture.
- Gateway fit: the Case limit plus the request overhead allowance is under the gateway's
  default body cap, read from its source.

## Acceptance

- FigQA's and TableQA's shapes capture as v2 Cases the connector and the scorer read back.
- Every refusal names the Case and the reason and never quotes base64 or a URL.
- Text-Benchmark Cases are byte-identical (existing capture and conversation tests unchanged).
- A local run of the importer on LAB-Bench FigQA, without committing the Benchmark, reports
  the real media types and the largest Case.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, five code and test files plus this ledger.
- **Commits:** `1b4222bd9` feat(screamingface-engine): save an eval's pictures inside the Case
  at import · `e26cabe84` feat(screamingface-engine): bound a picture Case by its size only, not
  per picture · plus this ledger close.
- **Gates:** `tests/unit/inspect/test_picture_cases.py` + `tests/unit/test_picture_case_limits_fit_the_gateway.py`
  31 passed (inspect extra); extra-less, the gateway-fit test passes and the inspect file skips.
  Neighbours unchanged and green: `test_capture.py`, `test_conversation_cases.py`,
  `test_one_envelope_reader.py`, `test_local_task_healthbench.py`, 104 passed. ruff, ruff format,
  pyright (with and without the inspect extra) clean on the touched files. Mutation checks, each
  restored: keeping `detail: auto`, dropping the cache-folder rule, trusting inspect's label and
  dropping the Case limit each fail the expected tests.
- **Real data (2026-10-26, the real import child, pinned `futurehouse/lab-bench` revision
  `5c77cec6`, nothing committed):** FigQA 181 Cases, one real JPEG each, picture then question,
  largest Case 4.19 MB, `cases.json` 330 MB. TableQA 244 Cases, 1 to 3 real PNGs each, largest
  Case 5.21 MB, `cases.json` 145 MB. inspect_evals' hard-coded labels were right at this pin.
  Reading and parsing `cases.json` alone peaks at 1,611 MiB (FigQA) and 727 MiB (TableQA) on a
  laptop, against a 2,560 MiB per-run budget.
- **Deviations:**
  - The 5 MB per-picture limit is dropped (owner decision, 2026-10-26): TableQA's Case 186 has
    a 5.21 MB picture, the Case limit already bounds the request, and the Claude API takes
    10 MB per image (5 MB is Bedrock's).
  - Picture files are read by the importer itself, not by inspect's `file_as_data_uri`: the
    type now comes from the bytes, so inspect's helper (a private `_util` module, which also
    fetches URLs) would only add a fetch path to refuse.
  - Two of the ticket's importer decisions were already true on main, so nothing changed for
    them: a fresh `INSPECT_EVALS_CACHE_DIR` per import, and capture after the solver chain.
  - Added after the review of #1450's canonical-encoding rule: the shared envelope reader
    (`candidate_input.py`) refuses a `data:` URI in any spelling but the standard one (lower-case
    type, no parameters, padded base64 with no whitespace). The connector sends a Case's part as
    written, so this makes one picture one spelling for every Case, hand-built too, without
    re-encoding on each call. Pinned by `test_a_media_part_in_another_spelling_is_refused`;
    dropping each of its three rules fails a named case.
- **Owner verify:** merge only after #1552 (OME-1679). On the first FigQA run, read the run's
  peak memory against the 2,560 MiB budget; if it goes over, loading only the selected Cases
  (OME-1675) is the fix.
