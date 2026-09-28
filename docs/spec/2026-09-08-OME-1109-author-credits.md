# OME-1109 — Published author credits

Status: approved for implementation on 2026-09-03 · Stack: scoreboard

## Problem

The multiple-author contract stores exact email addresses and publishes local parts. A repeated
address is therefore credited twice, while two distinct people with the same local part publish
as an indistinguishable pair such as `irina, irina`.

## Decisions

### D1 — One case-insensitive identity rule

An author's comparison identity is the case-folded complete address. Publication collapses
repeated identities in first-seen order and preserves the first submitted spelling. Comparison
never normalizes or rewrites the stored list.

### D2 — Domains appear only for actual local-part collisions

After duplicates are removed, publication groups authors by case-folded local part. A local part
that names one distinct identity stays local-part-only. Every identity in a group of two or more
publishes its complete address so the credit line is unambiguous. No domain is exposed on a row
without such a collision.

### D3 — Publication is the only transforming boundary

`ScoreSubmission.authors`, the database row, Python-mode DTO dumps, and the private staff JSONL
export retain the submitted list byte-for-byte and in order, including repetitions and casing.
The public JSON serializer alone collapses and disambiguates it.

### D4 — The ten-author limit counts distinct people

Validation applies the same complete-address comparison identity used by publication. Eleven list
entries containing one repeated identity are accepted because they credit ten people; eleven
distinct identities are rejected. The accepted value is not deduplicated on write. A separate
4 KiB serialized-field cap keeps repeated identities from making this public write unbounded; it
does not change which entries count as people.

### D5 — Submitter identity and authorization do not change

`submitted_by` remains a separate single identity and private-board authorization subject. This
unit does not merge it into the author list, grant authors access, or change its publication rule.

## Verification contract

- exact and case-variant duplicates publish once, preserving the first spelling;
- distinct addresses sharing a local part publish with domains, case-insensitively;
- non-colliding author addresses still publish only local parts;
- ten distinct people represented by eleven entries validate without rewriting the input;
- eleven distinct people fail validation;
- an oversized list of repeated identities fails the independent 4 KiB envelope;
- database storage and staff JSONL preserve the exact submitted list;
- leaderboard/history/score public JSON share the same serializer behavior;
- existing dedup correction, private ownership, portal display, and recipe-identity tests remain
  unchanged and green.

## Non-goals

- verifying co-author ownership or deliverability;
- changing SDK input, portal layout, content hashing, idempotency, or database schema;
- changing `submitted_by` validation or display (`OME-840` remains separate);
- introducing usernames or a global identity directory.
