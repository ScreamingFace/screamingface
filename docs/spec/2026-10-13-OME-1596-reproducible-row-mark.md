# OME-1596 — author and paper metadata, and a Reproduce button, on the leaderboard

**Status:** approved by the owner piece by piece, 2026-10-15 · **Parent:** E14 (`OME-1307`)
**Siblings:** SDK `OME-1613`, public docs `OME-1614` · **Date:** 2026-10-15
**Supersedes:** this file's 2026-10-13 draft (a reproducible / reproduced row mark), dropped.

## 1. Decisions this spec builds on

Recorded on the Linear issue (Irina and Filip, 2026-10-14/15): reuse `sf.evaluate(pinned_cache=…)`
to replay; `pinned_cache` is the user-facing name and `frozen_copy` stays internal; no reproduction
count is displayed; `authors_metadata` and `paper_metadata` are open objects with known keys,
bounds, matching and masking; the submitter edits them through the existing edit path; the board's
display of metadata is decided later by Irina.

## 2. Storage (piece 1, approved 2026-10-15)

- `scores` gains two nullable JSON columns:
  - `authors_metadata`: `{"<author email>": {"<key>": "<text>", …}, …}`.
  - `paper_metadata`: every `paper_metadata` key except `url`.
- `paper_metadata.url` is stored in the existing `paper_url` column (same validation, same edit log).
  On read, `paper_metadata.url` is filled from `paper_url`, so a client sees one object.
- `score_metadata_events` gains `old_authors_metadata`, `new_authors_metadata`,
  `old_paper_metadata`, `new_paper_metadata` (nullable JSON).
- One migration, `0021`, adds the six columns. No data is backfilled.
- Read schemas exclude both fields when null, so the private JSONL export's bytes do not change for
  existing rows (the rule `paper_url` already follows).
- **Edit semantics (owner, 2026-10-15):** an edit that sends an object **replaces the whole
  object**; `null` clears it; an absent field leaves it unchanged. This matches `authors` and
  `paper_url` today.

## 3. Validation (piece 2, approved 2026-10-15)

Same rules on submit and on edit (one shared validator, like `_validate_bounded_authors`).

| Rule | Detail |
|---|---|
| Object size | at most 20 keys in `paper_metadata`, and in each author's entry of `authors_metadata` |
| Keys | strings, 1–64 characters |
| Known keys | `full_name`, `institution`: text ≤ 200 · `title`: text ≤ 300 · `citation`: text ≤ 2,000 · `url`: the existing `paper_url` rules |
| Unknown keys (owner, 2026-10-15) | text ≤ 500 characters, a finite number, or a boolean; lists, objects and null are refused |
| Matching | every `authors_metadata` key is an email that appears in `authors` (after the same normalization `authors` uses) |
| Errors | 422 naming the field and the key, one per problem |

## 4. Publication and masking (piece 3, approved 2026-10-15, option A)

| Where | What appears |
|---|---|
| Public API (`GET /v1/scores/{id}`, spec history, any later row field) | `authors_metadata` keyed exactly as that author appears in the published `authors` list (`_publish_authors`, `schemas.py:280`): the local part, or the full address only when two authors share a local part. `paper_metadata` in full, with `url` filled from `paper_url`. Unknown keys included. |
| Private-board scores | existing visibility rules, unchanged: submitter only |
| Staff export (private JSONL) | full email keys, unmasked, like `authors`; both fields excluded when null |
| Edit log | owner and operators only (unchanged); full before/after objects |
| Portal | displays nothing new (display is Irina's decision) |

- Masking is a JSON serializer on the read schemas (like `Authors`), never a change to stored data, so
  a later switch to "not public" or "known keys only" is a serializer change with no migration.
- Example: authors `["ana@uni.edu", "bo@lab.org"]` publish as `["ana", "bo"]` and
  `authors_metadata` as `{"ana": {"full_name": "Ana Silva", "institution": "MIT"}}`.

## 5. Pinned cache lookup (piece 4, approved 2026-10-15, option 3)

- **Route:** `GET /v1/scores/by-pinned-cache/{frozen_copy_id}`, public, no identity needed.
  Returns the score that names this copy: score id, benchmark id and revision, url4, `answer_seed`,
  score, `total_questions`, `case_digest`, `capture_status`.
- **404, identical body,** for an unknown id, a malformed id, and a score on a private board (or one
  whose board turned private), so a caller cannot learn that a private copy exists. Same rule as
  `GET /v1/scores/{id}`.
- **One copy, one score (owner, 2026-10-15):** a submission naming a `frozen_copy_id` that another
  score row already names is refused with 422 (`frozen_copy_claimed`). A same-owner resubmit that the
  board deduplicates onto the same row is not a second claim and is accepted, as today.
  - Enforced by a unique index on `scores.frozen_copy_id` (null allowed many times), so two concurrent
    submissions cannot both win. The index is created in migration `0021`.
  - **Before the migration ships:** check dev and production for existing duplicate `frozen_copy_id`
    values; the index cannot be created over duplicates. If any exist, stop and ask the owner.
- The lookup is read-only and returns no copy contents; the copy itself stays in the gateway.

## 6. Reproduce button and the count line (piece 5, approved 2026-10-15)

- **Row data:** `RankedLeaderboardEntry` gains `pinned_cache: str | None`, computed per request like
  `on_pareto_frontier` (not on `LeaderboardEntry`, so private `my_submissions` and the export are
  untouched). It is the score's `frozen_copy_id` only when `capture_status == "complete"`, else
  `null`. Read for the page's rows in the same snapshot as the rest of the page.
- **Button:** in the Run column, a **Reproduce** button stacked under **Copy url4**, shown only when
  the row's `pinned_cache` is set. It copies:
  ```python
  import screamingface as sf
  result = sf.evaluate(pinned_cache="<id>")
  ```
  with the same copied/failed feedback as the existing Copy button and a one-line hover ("Replays this
  run's recorded answers at $0 and checks the published score"). SFDS: square corners, existing button
  recipe, no new colours.
- **Switch (owner, 2026-10-15):** a constant in `portal/benchmark.js`, off. A one-line PR turns it on
  after the SDK release with `evaluate(pinned_cache=…)` (`OME-1613`). The portal has no way to read
  server settings, and the switch flips once, so a code constant was chosen over a `SCOREBOARD_*`
  setting or a config endpoint. The API field and the lookup ship regardless.
- **Count line:** remove "Reproduced N times" from the per-submission page (`portal/spec.js`,
  `renderReproduced`). The API keeps returning `reproduction_count`.

## 7. Tests and rollout (piece 6, approved 2026-10-15)

**Tests, written first and failing before the code** (structured checks only: parsed JSON, parsed
HTML, model fields; no regular expressions or substring searches; no prior test edited without owner
approval):

- Storage and validation: every bound, key format, value type and the matching rule; each 422 names
  the field and key; edits replace whole objects, `null` clears, removing an author drops their
  metadata; edit-log rows carry before and after.
- Publication: masked keys in public JSON, including two authors sharing a local part; full addresses
  in the staff export; export bytes unchanged for an existing row without metadata.
- Lookup: fields for a public captured score; the identical 404 for unknown, malformed and private;
  a second claim on a copy refused with 422; a same-owner deduplicated resubmit accepted; two
  concurrent claims cannot both succeed (unique index).
- Rows and portal: `pinned_cache` only on complete-capture public rows; button only with the switch
  on; exact snippet text; no "Reproduced N times".

**Rollout:**

1. Before merge, query dev and production for duplicate `frozen_copy_id` values; any duplicate stops
   the rollout for an owner decision.
2. Merge, deploy to dev, verify, then production, with the switch **off**.
3. Release the SDK (`OME-1613`), then turn the switch on.
4. Docs (`OME-1614`) ship with or after the SDK release.
