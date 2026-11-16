---
ticket: OME-1926
stack: aigateway
status: in_progress
started: 2026-11-15
finished:
---

# gateway-request-cap — raise the AIGateway request-body cap to 12 MiB

## Intent

url4 admits up to 8,000,000 decoded attachment bytes (`MAX_ATTACHMENT_BYTES`, PR #1588). Base64
makes that 10,666,668 bytes on the wire, more than the gateway's 8 MiB (8,388,608) default body
cap, so a legal 6.5 MB image gets 413 `request_too_large`. Owner decision (HupBaHa's review,
2026-11-13): the default becomes 12 MiB = 12,582,912, leaving 1,916,244 bytes for prompt and
JSON envelope. Parent epic OME-1529.

## Planned changes

- `apps/aigateway/src/aigateway/config.py` — `max_request_bytes` default 12 MiB, WHY/INVARIANT.
- New `apps/aigateway/tests/unit/test_request_cap_fits_url4_attachments.py`.
- Owner-approved prior-test edits (2026-11-15): `test_body_cap_route.py` (constant + rename to
  `..._twelve_mebibytes` + docstring) and `test_frozen_copy_entry_cap.py` (constant + docstring).
- Docs: `public-docs/src/pages/learn/Url4FilesPage.vue`, `docs/spec/2026-11-11-attachment-blob-refs.md`,
  `docs/spec/2026-10-20-harden-file-intake.md`,
  `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md`,
  `docs/diagrams/file-input-path.svg` (+ PNG re-render).

## Test plan

- Default cap is 12,582,912 and fits 8,000,000 bytes base64 (10,666,668) with room to spare.
- Real app, default cap: a 12,582,912-byte body passes the size gate (route's own 400).
- One more byte: 413 `request_too_large`, `limit_bytes == 12582912`.
- `frozen_copy_max_entry_bytes == 12,582,912 + FROZEN_COPY_RESPONSE_HEADROOM_BYTES` = 14,680,064.

## Acceptance

- Gates green except the append-only check on the two approved files (approval JSON from owner).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `docs/diagrams/file-input-path.png` re-rendered and the
  frozen-copy INVARIANT comment in `config.py` (10 MiB -> 14 MiB).
- **Commits:** see PR (single commit on `OME-1926-gateway-request-cap`).
- **Gates:** `run_gates.py aigateway` append-only check fails on exactly the two approved files
  (owner approval JSON pending); with `--skip-append-only` ruff, format, pyright,
  check_no_enterprise, pytest+coverage ALL GREEN. `run_gates.py repo --base origin/main` ALL GREEN.
- **Deviations:** the two prior-test edits are owner-approved (2026-11-15); push waits on the
  owner's approval JSON. `test_body_cap_route.py` docstring keeps its MMMU basis line (scope was
  the 8 -> 12 MiB figure only). The 2026-10-20 and 2026-11-11 specs got a dated supersede note
  rather than a rewrite of their history.
