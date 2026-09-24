---
id: OME-1215
linear_url: https://linear.app/openmined/issue/OME-1215/gate-docstasks-mirror-status-against-the-ledger-then-sweep-the-stale
status: in_progress
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
  case-insensitively**, and asserts only what a ledger can PROVE:
  `done` ⇒ mirror NOT in `{backlog, todo}`; `blocked` ⇒ a STOP state;
  `in_progress`/`planned` ⇒ anything but `done`.
- Wired into the `repo` stack of `.claude/sdlc.local.md` and into the `mirror-status` job
  of `.github/workflows/repo-checks.yml`.
- A mirror with no ledger is reported, never failed.

The sweep of the flagged mirrors follows the gate, and never weakens the rule to shrink
itself.

Ledger: `docs/work/2026-09-17-OME-1215-mirror-status-gate.md`

## Status — round 2, unblocked

The owner answered the round-1 STOP: the ticket's own rule table (`ledger done -> mirror
done`) contradicts CLAUDE.md, which makes **Linear** the status authority. A ledger is per
UNIT of work and a mirror is per TICKET, so a finished unit on an open ticket is legal. The
rule is narrowed to `ledger done -> mirror NOT in {backlog, todo}`; the gate never forces a
mirror to `done`, and the 24 conflicts were **not** swept.

Re-verified RED with the narrowed rule on the pre-sweep `origin/main` tree: **exit 1, 22
genuine offenders** (122 under the wide rule — the 100 dropped were its false positives).
19 of the 22 were real drift and were already fixed. The remaining three (`OME-887`,
`OME-908`, `OME-906`) are verified counterexamples to the rule itself, each read from
Linear, and are waived with that evidence inline and pinned to the exact status pair
checked — not swept, because for two of them the mirror is the correct side. `OME-906`'s
mirror was closed to match Linear's `Done`.

`run_gates.py repo` is 4/4 green; the gate now runs in CI on every `docs/tasks/**` and
`docs/work/**` change. Detail: the ledger.
