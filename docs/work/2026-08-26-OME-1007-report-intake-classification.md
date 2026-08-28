---
ticket: OME-1007
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1007 — Classify content server-side and reject Class C

## Intent

Spec §4: the service decides whether a report is an envelope or carries content, and a report
carrying content is rejected with `422` rather than stored, redacted, or trusted. This is the
constraint that lets every later item stay simple — there is no bundle store, no TTL sweep and
no Access-gated read surface in this service precisely because prompt-bearing material never
gets past the request path.

The classifier is fail-closed in the sense the review spec means: it never consults
client-declared intent, and undeclared content is still content. It is *not* fail-closed in the
sense of rejecting anything large — plan §5 and §11/#11 are explicit that scoping the
oversized-leaf detector over `/client` and `/context` would make a 300-byte `client.version` a
`422`, contradicting §2.4's normative caps table.

## Planned changes

- `apps/report-intake/src/report_intake/classification/__init__.py`, `.../content.py` — the
  classifier. Two exported entry points, per plan §2.7: `classify_report(document) -> Verdict`
  for the request path and `scan_text(text) -> str | None` for `OME-1009`'s fail-closed re-check
  on a rendered ticket body.
- `apps/report-intake/src/report_intake/routes/reports.py` — classify between `bind` and the
  pipeline, so a rejected report is refused before anything downstream could persist it.
- `apps/report-intake/src/report_intake/reports/pipeline.py` — `Submission` carries the server's
  verdict; `BindOnlyPipeline` echoes it instead of hardcoding a placeholder.
- `apps/report-intake/src/report_intake/reports/caps.py`, `.../reports/binding.py` — publish the
  RFC 6901 escape as `escape_pointer` rather than let a third private copy of it appear.
- `apps/report-intake/tests/unit/test_classification.py` — new.
- `apps/report-intake/tests/unit/test_reports_route.py` — the route-level rejection cases.
- `apps/report-intake/README.md`, `apps/report-intake/docs/complexity-baseline.md` — refreshed.

## Test plan

- A report whose `error.details` carries a chat transcript is rejected `422`, and the detail
  says content is not accepted.
- An envelope-only report — including one with a traceback and a WebSocket close cause — is
  accepted, because a classifier that rejects ordinary reports is worse than no classifier.
- The rejection detail names the pointer and **never** echoes a value from the report: the same
  invariant `binding.py` holds for pydantic errors.
- Content that truncation would have removed is still rejected — the classifier reads `scanned`
  (pre-truncation), so truncating is not a way to smuggle a prompt past the check.
- A 300-byte `client.version` and a 2 KiB `note` are accepted, not rejected — plan §11/#11.
- An oversized leaf under `/error/details` or `/error/cause` is content; the same string under
  `/client` or `/context` is not.
- `scan_text` finds the string-level markers and nothing structural, since `OME-1009` hands it a
  rendered string with no pointers.
- Nothing reaches the pipeline when the verdict is content.

## Acceptance

- `classify_report` and `scan_text` exported as plan §2.7 names them.
- `POST /v1/reports` answers `422` `application/problem+json` from `content_rejected()` — no
  ad-hoc status, no new catalogue entry.
- The accepted verdict travels to the pipeline rather than being re-invented as a literal at the
  point of response rendering.
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` green.

## Outcome

- **Actual files:** as planned, plus `src/report_intake/core/pointers.py` (see deviations).
  New: `classification/__init__.py`, `classification/content.py`, `core/pointers.py`,
  `tests/unit/test_classification.py`. Edited: `routes/reports.py`, `reports/pipeline.py`,
  `reports/caps.py`, `reports/binding.py`, `tests/unit/test_reports_route.py`, `README.md`,
  `docs/complexity-baseline.md`. `main.py`, `config.py`, `routes/ready.py` and
  `core/problem_catalogue.py` are untouched — this item needs no new status and no new setting.
- **Commits:** orchestrator-owned.
- **Gates:** `uv run .claude/scripts/run_gates.py report-intake` → ALL GATES GREEN.
  161 passed (31 new: 27 in `test_classification.py`, 4 at the route), ruff check + ruff
  format --check clean, pyright 0 errors, coverage 99.56% (`classification/content.py` 100%).
  Complexity high-water marks unmoved: C901 7, PLR0915 18, PLR0912 6, PLR0911 3.
- **Where the classifier runs, and why it is not in the pipeline.** Spec §4 rejects content
  rather than storing it, so the refusal happens at the route between `bind` and
  `pipeline.submit` — before anything capable of persisting is reached. A classifier called
  from inside `StorePipeline` would be one edit away from persist-then-classify, and the
  invariant would then rest on the order of two statements nobody re-reads.
- **Deviations:**
  - **`Submission` gained a `classification` field.** `OME-1006` froze it as
    `(bound, idempotency_key, caller_email)` with the pipeline hardcoding `"envelope"`. The
    verdict is the server's and is decided before the seam, so it travels as the decided value:
    `OME-1008` persists `submission.classification` into §2.3's column and the response echoes
    the same source, instead of a literal written at two places that can disagree. Only
    `envelope` ever reaches a pipeline — `content` is a 422 that never gets there.
  - **`escape_pointer` moved to `core/pointers.py`.** The RFC 6901 escape existed twice already
    (`caps._escape` and an inline copy in `binding._pointer`); the classifier would have been the
    third. Both existing copies now call the shared one. No behaviour change — `caps.py` line
    numbers shift, which is why the complexity baseline was refreshed.
  - **`oversized-leaf` threshold is 1 KiB**, a number the plan left open. Scoped to
    `/error/details` and `/error/cause` exactly as §5 and §11 conflict 11 require; everywhere
    else a long string has a cap, not a verdict.
