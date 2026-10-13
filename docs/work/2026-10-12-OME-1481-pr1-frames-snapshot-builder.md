---
ticket: OME-1481
stack: screamingface-engine
status: in_progress
started: 2026-10-12
finished:
---

# OME-1481-pr1-frames-snapshot-builder — freeze FRAMES' gold Wikipedia articles into one pinned snapshot file

## Intent

FRAMES ships Wikipedia links, not text, and the articles-given setting pastes the gold
articles into every prompt. This unit adds the builder that fetches each gold article once,
at its last revision before 2024-09-19, turns the rendered page into plain text (body,
headings, tables and infoboxes kept; references, navigation boxes, hatnotes and images
dropped) and writes one JSONL snapshot the owner publishes on Hugging Face. The FRAMES Task
(PR 2) then pins that snapshot by commit and sha256. Decisions 6 to 10 on OME-1481 (10: serve the drawn text, measured 2026-10-13).

## Planned changes

- `apps/screamingface-engine/scripts/frames_snapshot.py` — new, stdlib only: link cleanup,
  revision resolution at the cut-off, HTML → text, the JSONL writer, the CLI. It lives in
  `scripts/`, not in `local_tasks/frames/`, because the Task package's every `.py` is hashed
  into the Benchmark Revision (`task_source=`): a builder there would move the revision on an
  edit that changes no Case. The snapshot's own sha256, pinned by the loader, is what covers
  the text.
- `apps/screamingface-engine/tests/unit/test_frames_snapshot.py` — new
- `apps/screamingface-engine/tests/unit/fixtures/frames_snapshot/` — real article HTML
  excerpts (CC BY-SA 4.0, attributed in a README beside them)
- `docs/tasks/2026-10-12-OME-1481-frames-articles-given.md` — mirror

## Test plan

- HTML → text on real revisions: the infobox survives as `label | value` rows, a wikitable
  survives as pipe rows, headings keep their level, and references, citation markers,
  navboxes, hatnotes, images, styles and the References/External links sections are gone.
- Link cleanup on every non-standard spelling FRAMES actually contains: mobile host,
  missing scheme, fragment, percent-encoding, two URLs glued with ", ", `index.php?title=`,
  the search URL and the `w.wiki` short link (explicit table), `simple.wikipedia.org`.
- Revision resolution (fake API): the last revision before the cut-off wins; a redirect at
  the cut-off is followed; a page renamed after the cut-off is found through the move log by
  its page id, never through today's redirect (which can be re-pointed: The Beatles
  discography → The Beatles); only the first rename after the cut-off counts; a page with no
  revision before the cut-off is refused by name; all refusals are reported together, and
  nothing is written.
- Known deleted pages (decision 9): the two named pages are listed on their question row as
  missing, never refused; any other missing page is still refused.
- The two odd links: a title percent-encoded twice (question 764) and a note pasted into the
  URL (question 644) each resolve to their one page.
- Each article row flags the years after the cut-off that only today's templates wrote
  (`years_from_templates`), so the drift decision 10 accepts stays visible per article.
- Writer: rows sorted, byte-identical on a re-run, each row lists every link spelling that
  maps to it, every revision timestamp before the cut-off.

## Acceptance

- One command builds the snapshot from the pinned questions file and prints its sha256,
  article count and prompt-length summary; it refuses rather than drop an article.
- Tests above pass in the extra-less Engine lane; ruff and pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `apps/screamingface-engine/scripts/frames_snapshot.py`,
  `apps/screamingface-engine/tests/unit/test_frames_snapshot.py`, fixtures under
  `tests/unit/data/frames_snapshot/` (not `fixtures/` as planned).
- **Commits:** the builder; then the move-log rename lookup, the known deleted pages, the two
  odd links and the per-article `years_from_templates` flag (2026-10-13).
- **Gates:** `tests/unit/test_frames_snapshot.py` 39 passed; ruff check + format and pyright
  clean on both files. Full suite left to CI.
- **Deviations:** which page held a title at the cut-off is read from the move log FIRST,
  by page id (the first full build refused 5 pages swapped after the cut-off, e.g. "Edward
  II of England", whose title today holds its old short-name redirect); renamed pages never
  go through today's redirect, and a page moved away that is younger than the cut-off is
  skipped (a vandalism cleanup on "Dolly Parton" in August 2026) (the
  redirect test from the first commit was replaced: "The Beatles discography" now redirects
  to "The Beatles"). The builder file is 658 lines, over the 450-line guideline. Not yet run
  against live Wikipedia: the full build and the snapshot publish are still to do.
