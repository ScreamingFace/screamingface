---
id: OME-1215
linear_url: https://linear.app/openmined/issue/OME-1215/gate-docstasks-mirror-status-against-the-ledger-then-sweep-the-stale
status: blocked
type: task
priority: medium
labels: [repo]
created: 2026-09-17
closed:
---

# Gate docs/tasks mirror status against the ledger, then sweep the stale ones

`docs/tasks/` mirrors drift out of sync with their `docs/work/` ledgers — 20+ sit at
`in_review` for units whose ledgers say `done`. `OME-1133` hand-swept a batch; it drifted
again because nothing notices the disagreement.

The deliverable is the gate:

- `.claude/scripts/check_mirror_status.py` pairs mirrors with ledgers **by ticket id,
  case-insensitively**, and asserts `done` ⇒ `done` + `closed:` set, `blocked` ⇒ a STOP
  state, `in_progress`/`planned` ⇒ anything but `done`.
- Wired into the `repo` stack of `.claude/sdlc.local.md` and into
  `.github/workflows/repo-checks.yml`.
- A mirror with no ledger is reported, never failed.

The sweep of the flagged mirrors follows the gate, and never weakens the rule to shrink
itself.

Ledger: `docs/work/2026-09-17-OME-1215-mirror-status-gate.md`

## Status

**Blocked on an owner decision.** The gate is built, RED-verified on `origin/main` (122
offenders) and mutation-tested (18/18 killed). 97 of the 122 were swept after cross-checking
every ticket against Linear. The remaining 25 are left untouched: their ledgers say `done` while
Linear still says `In Progress`/`In Review`, because a ledger is per unit of work and a mirror is
per ticket. The gate is deliberately NOT wired into the gate lane until that is settled — a check
that is red on `main` blocks every PR. Detail and the exact question: the ledger.
