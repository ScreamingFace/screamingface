# External result metadata

Parent: [E20](https://linear.app/openmined/issue/OME-1309). The owner authorized this
metadata increment on 2026-11-03. It is independent of the display PR #1644.

Owner chose option A on 2026-11-03: metric and dates are public, including on private
boards; `attached_by` stays internal. The existing public-field privacy guard is
updated for exactly these three public fields and explicitly forbids `attached_by`.

## Contract

External results already have a score, source identifier, source URL, first import
timestamp and optional source-specific JSON. Add these named fields:

| Field | Meaning |
| --- | --- |
| `metric_name` | The metric actually reported by the source; up to 128 characters. |
| `observed_at` | When the source was read, with an explicit time zone. Not the model run date. |
| `attached_by` | Internal attribution supplied by the trusted importer, up to 255 characters. Not proof of identity or permission. |
| `last_imported_at` | Server-recorded time of the latest successful import. |

The first three fields are optional input; only metric and observation date are
public output. `last_imported_at` is output only. Existing `imported_at` continues
to mean first import. New fields are nullable
and are not backfilled: missing facts must not be invented from a board's metric,
the importing machine's user, or the migration date. Old input files still work.

Text is trimmed, nonblank when supplied, and cannot contain control characters.
The existing source URL and score validation continue to apply.

Each import is a complete replacement of the current source observation, matching
the existing score/source URL/JSON behavior. Omitted provenance is stored as null,
not inherited from a previous score: an old observation date must never silently
describe a new number. Importers should resend all known fields. The row ID and
first import date stay stable; last import time advances on each successful import.
Batch imports remain atomic, including their timestamps and provenance.

The public leaderboard API exposes metric and dates on baseline rows. Attribution
is stored in its dedicated database column and is absent from the public response
schema and serialized responses, on public and private boards alike. Do not copy
attribution into the existing public free-form `metadata`. This does not add a
public write endpoint or grant permissions. The future manual entry path must
derive attribution from its authenticated actor, not trust user text.

## Scope

Storage, import validation, public read API, migration, tests and importer documentation.
No UI changes, production import, source matching policy, manual-entry permissions,
edit history or dead-link checking. Historical versions remain a separate E20 unit.

## Acceptance

- Metric and dates survive JSON ingestion, storage, re-import and public API reads.
- Attribution survives storage and re-import but never enters a public read DTO.
- Legacy inputs and old rows work with unknown fields null.
- Invalid text/time zones fail before persistence.
- Duplicate imports update one row; failed batches roll back all changes.
- The additive migration works on a populated database and leaves old values intact.
