---
ticket: OME-1599
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-22
finished:
---

# node-auth-spec — draft the url4 node-to-node authentication spec

## Intent

Spec #1450 (`OME-1535`, F1/F1b) defers remote `url4://` blobs (C2) and remote-node calls (C6)
until a node-to-node authentication spec exists, and keeps the #1521 peer allowlist empty until
then. This unit drafts that spec for `OME-1599`: threat model, options, a recommended design,
identity and key discovery, inbound authorization, replay protection, rotation, typed `x.` failure
codes, and how C2/C6 are enabled alongside the #1521 destination guard. Design only; no code.

## Planned changes

- `docs/spec/2026-10-22-OME-1599-node-to-node-auth.md` (new, DRAFT)
- `docs/work/2026-10-22-node-auth-spec.md` (this ledger)

## Test plan

- Spec only. The spec itself names the tests both nodes need (§9). Gates: `git diff --check`,
  `python3 .claude/scripts/check_mirror_status.py`.

## Acceptance

- The spec covers every item of the F1b bar: outbound identity, credential transport and rotation,
  inbound authorization, replay behaviour, typed auth failures and tests at both nodes.
- It is marked DRAFT and lists the open questions for Kevin (url4 grammar owner).
- Branch pushed; no PR opened (the orchestrator decides).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see branch `node-auth-spec`.
- **Gates:** `git diff --check` clean; `check_mirror_status.py` run (see commit).
- **Deviations:** url4 Part B §3.5 (`URL4-Auth-Token`) text was not available locally, so the
  header's binding is proposed and raised as open question Q1 rather than quoted.
- **2026-10-28 revision (approved by Sergey):** rebased onto `origin/main` (`6ea6a0011`); code facts in
  §1 re-verified. Added a "Decisions requested from Kevin" checklist at the top and, in §10, a
  working assumption per question (conservative, consistent with #1450), its consequence, and what
  changes if Kevin answers otherwise, so review does not need Kevin live. Six questions (Q1–Q6) go to
  Kevin; the draft's former Q7 (consent hooks) is outside `OME-1599`'s scope and is now a note left
  to Part C. Linear `OME-1599` had no comments listing the questions; the six are the draft's own.
  Still DRAFT; no PR.
