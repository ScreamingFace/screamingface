---
ticket: OME-1543
stack: repo
status: done
started: 2026-10-21
finished: 2026-10-21
---

# file-refs-carry-plan — implementation plan for carrying file refs through url4 fan-out, reduce and iteration

## Intent

Write the TDD implementation plan for `OME-1543` against the owner-locked file-input design (F1–F3 of
the `OME-1535` spec, #1450, locked 2026-10-21): an ordered, run-scoped `attachments[]` side-channel,
`Payload` stays `str`, no string scanning, every model-calling node emits `[attachments…, text]`.
Plan only: no code, no PR, no sub-issues filed.

## Planned changes

- `docs/plan/2026-10-21-OME-1543-file-refs-carry-plan.md` (new)
- `docs/work/2026-10-21-file-refs-carry-plan.md` (this ledger)

## Test plan

- Docs-only unit; the plan itself names every failing test to write first.
- Gate: `uv run .claude/scripts/run_gates.py repo` (append-only check included).

## Acceptance

- Plan names exact files, test names and order; splits url4 vs engine work; lists proposed
  sub-issues (not filed); records the conflicts between the ticket body / #1482 and F1–F2.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see branch `file-refs-carry-plan`.
- **Gates:** `run_gates.py repo` green (see final report).
- **Deviations:** the ticket body ("refs stay text tokens, recognised") and open PR #1482
  (`ResolvedBlob` str subclass; allow-listed `url4://` blob fetch) contradict owner-locked F2/F1.
  The plan follows F1–F3 and lists the required deltas as open decisions.
- **Revision (2026-10-21):** owner decisions D1–D6 resolve Q1–Q5. #1482 is amended before merge, so
  U0 is a rebase plus a check (no `ResolvedBlob` / remote-fetch undo); every `url4://` blob ref is
  `x.remote_blob_unsupported` (D1); envelope attachments go on the last user message (D3); C8 blob
  is text only (D4); failed `;optional` blob fails the run (D5); judge text-only (D6). Added U3
  tests for D1 self-authority, D4 and D5. Q6 (ticket body rewrite at PR-open) and the `OME-1540`
  dependency stay open.
- **Revision 2 (2026-10-21, F1b):** governing spec now includes F1b (`3c6ae278e`; PR #1450 comment;
  Linear `OME-1544` re-parented under `OME-1529`). The plan reuses #1482's
  `url4.dag.attachment.Attachment` (no second definition; U1 reduced to a one-definition test; the
  engine builder takes bytes from `Attachment.body` and derives `kind`); adds a per-run file cache so
  each file is fetched and verified once (§2.8); adds `https://` `src=` sources through the
  `OME-1544` guard, non-text hashed into the run store and attached (§2.7, U3b; sub-issue A also
  blocked by `OME-1544`); records the local spelling `/blob/sha256/<hex>` with bare
  `blob:sha256/<hex>` local, and takes `$x*(…)` over a blob binding into scope (§2.9). New open Q7:
  `https://` attach scope (`src=` only) and write-through of hashed bytes to the engine store.
