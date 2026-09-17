---
ticket: OME-1215
stack: repo
status: blocked
started: 2026-09-17
finished:
---

# OME-1215 — Gate docs/tasks mirror status against the ledger, then sweep

## Intent

`docs/tasks/` mirrors drift out of sync with their `docs/work/` ledgers: 20+ mirrors sit at
`status: in_review` for units whose ledgers say `done` and whose PRs merged weeks ago.
`OME-1133` hand-swept a batch and it drifted again, because nothing in the repo notices the
disagreement. CLAUDE.md rule 1 ("status closed in BOTH") is currently unenforced. The
deliverable is the enforcement, not the sweep.

## Design decisions

- **New script, not an extension.** `.claude/scripts/` holds `run_gates.py`,
  `check_loop_parity.py`, `check_layering.py`, `audit_dependabot_ignores.py`. None of them
  touches `docs/`; there is no docs-consistency script to extend, so this adds
  `.claude/scripts/check_mirror_status.py` as the first one.
- **`repo` stack added to `.claude/sdlc.local.md`.** The card named no stack for docs-only
  changes, although `docs/work/TEMPLATE.md` already offers `repo` as a ledger `stack:` value
  and `.github/workflows/repo-checks.yml` is the matching CI lane. The new stack has
  `root: .`, no `test_globs` (the repo lane's own tests live under `.claude/scripts/tests/`
  and are run as a gate), and gates = loop parity + mirror status + the scripts' unit tests.
- **Pairing by ticket id, case-insensitively.** `OME-\d+` is read from frontmatter
  (`ticket:`/`id:`) when present, else from the filename, then upper-cased. Filenames do NOT
  line up: `docs/tasks/2026-08-04-ome-734-dependabot-triage.md` is lowercased while its
  ledger is not.
- **Multiple ledgers per ticket:** the newest one (by filename date, then name) decides,
  because a follow-up ledger reopening a unit is the current truth.
- **Statuses are normalised**: lower-cased, trailing `#` comment stripped, `-`→`_`. Real
  values in the tree include `In Progress`, `Backlog`, `in-progress` and
  `in_review   # matches Linear; …`.
- **Ledger statuses outside the ticket's rule table** (`in_review`, `reverted`, and any
  future value) are REPORTED, never failed. The rule table is implemented literally; it is
  not widened by guesswork. `complete`/`completed` are accepted as spellings of `done`.
- **A mirror with no ledger is reported, not failed** (per the ticket).

## Rule implemented

| ledger | mirror must be |
| -- | -- |
| `done` (`complete`, `completed`) | `done` AND `closed:` set (not empty/null) |
| `blocked` | `blocked` or a STOP state (`needs-owner`, `design-session`) |
| `in_progress` / `planned` | anything except `done` |

## Planned changes

- `.claude/scripts/check_mirror_status.py` (new)
- `.claude/scripts/tests/test_check_mirror_status.py` (new)
- `.claude/sdlc.local.md` — add the `repo` stack
- `.github/workflows/repo-checks.yml` — add the mirror-status job
- the flagged `docs/tasks/*.md` mirrors (the sweep)

## Test plan

RED first, against a temp docs tree:

- pairing works when mirror filename is lowercased and the ledger is not
- pairing prefers frontmatter ticket id over the filename
- ledger `done` + mirror `in_review` → violation
- ledger `done` + mirror `done` but `closed:` empty → violation (half-closed)
- ledger `done` + mirror `done` + `closed:` set → clean
- ledger `blocked` + mirror `done` → violation; + mirror `blocked` → clean
- ledger `in_progress` + mirror `done` → violation; + mirror `in_review` → clean
- mirror with no ledger → reported, exit 0
- ledger status outside the table → reported, exit 0
- `In Progress` / `in-progress` / trailing-comment statuses normalise
- newest ledger wins when a ticket has several

## Acceptance

- The check goes RED on `origin/main` naming the offenders (recorded below).
- After the sweep, `uv run .claude/scripts/run_gates.py repo` is green.
- No mirror is stamped `done` to clear the check; genuinely unclear ones are reported here.

## RED run (before the sweep)

The check was run on the tree as it stood at `origin/main` (3641a9a1) BEFORE any mirror was
touched. It failed, exit 1, naming every offender:

```
✗ mirror status gate — 122 mirror(s) disagree with their ledger:
  OME-303  [ledger-done-mirror-not-done]
    mirror: docs/tasks/aigw/2026-08-12-OME-303-per-provider-attempt-usage-accounting.md  (status: in_progress)
    ledger: docs/work/2026-08-07-OME-303-per-provider-call-usage-accounting.md  (status: done)
    ledger is done; mirror is 'in_progress' — close the mirror
  OME-305  [ledger-done-mirror-not-done]
    mirror: docs/tasks/aigw/2026-08-03-OME-305-global-request-cache-fingerprint.md  (status: in_progress)
    ledger: docs/work/aigw/2026-08-05-OME-305-pr-ci-test-isolation.md  (status: done)
  OME-369  [ledger-done-mirror-not-done]
    mirror: docs/tasks/2026-07-09-append-only-line-diff.md  (status: in_review)
    ledger: docs/work/2026-07-09-OME-369-append-only-line-diff.md  (status: done)
  … 119 more …
- 102 note(s), not failures:
    89 × no-ledger · 12 × ledger-status-unclassified · 1 × no-ticket-id
```

Breakdown of the 122:

| reason | count |
| -- | -- |
| `ledger-done-mirror-not-done` | 110 |
| `ledger-open-mirror-done` | 10 |
| `ledger-status-unclassified` (note, not a failure) | 12 |
| `ledger-done-mirror-not-closed` | 1 |
| `ledger-blocked-mirror-not-stopped` | 1 |

The pairing is doing real work, not filename matching: `docs/tasks/2026-07-09-append-only-line-diff.md`
and `docs/tasks/2026-07-21-precommit-hookspath.md` carry no ticket in their filename at all and
paired through frontmatter; `docs/tasks/2026-08-04-ome-734-dependabot-triage.md` paired
case-insensitively with an upper-cased ledger; `docs/tasks/aigw/…` paired across subdirectories.

## Mutation testing

18 mutants of `check_mirror_status.py`, **18 killed, 0 survived** (harness: flip one production
behaviour, run the suite, require a named failure, restore). Covered: case-insensitive pairing,
comment stripping, case folding, the `complete`/`completed` aliases, the `closed:` unset set,
each of the three rule branches, newest-ledger-wins, frontmatter-beats-filename, notes-are-not-
failures (twice — as a failure, and with its status fields transposed), the exit code, numeric
ticket ordering, recursive discovery, the TEMPLATE/README skip, and the report naming the mirror
path. No assertion anywhere reads `repr()` of an object; every one walks named fields.

## The sweep — and where it stops

**Swept (97 files, every one cross-checked against Linear via MCP):**

- **87 mirrors** whose ledger says done AND whose Linear issue is genuinely `Done`: `status: done`
  plus `closed:` sourced from the ledger's own `finished:` date (its filename date when `finished:`
  was blank). This is the drift the ticket is about — 42 of them were the `in_review` mirrors,
  45 more were `in_progress`, `backlog`, `todo` or `pick_immediately`.
- **10 ledgers** (`OME-525 555 556 564 565 566 567 959 1094 1097`) flagged
  `ledger-open-mirror-done`: here the MIRROR was right and the LEDGER was the stale side — all ten
  issues are `Done` in Linear and their mirrors already said so, while the ledger still read
  `in_progress` with an empty `finished:`. Closed with each issue's real Linear `completedAt` date.
  Not in the ticket's wording ("fix every mirror it flags"), but fixing the mirror instead would
  have falsified it.

**NOT swept — 25 flagged items, left exactly as they are (see STOP below).**

## STOP — the rule's premise does not hold for 25 of the 122

The ticket's rule table reads `ledger done -> mirror done`. That treats a done ledger as proof the
ticket is finished. For 97 of the 122 it is. For **24** it is not: the ledger says `done`, and
Linear — which CLAUDE.md rule 1 makes the status authority — says the issue is still `In Progress`
or `In Review`. The mirror currently agrees with Linear. Stamping those mirrors `done` would make
the repo say a thing Linear denies, and five of them (`OME-1042`, `OME-1161`, `OME-1177`,
`OME-1191`, `OME-1195`) have ledgers dated 2026-09-16/17 — work in flight this week.

The cause is structural, not data rot: **a ledger is per UNIT of work, a mirror is per TICKET.**
A ticket with several units (`OME-887` has seven ledgers, `OME-1177` four, `OME-1161` three) can
have every unit done and still be open. Two reformulations were measured and both are worse:

- *all ledgers must be done, not just the newest* — still flags 23 of the 24, and loses 16 true
  positives. Strictly worse on both sides.
- *waive the 24 by name* — that is the weakening the ticket forbids.

The 25th is `OME-906`: ledger `blocked`, mirror `in_progress`, Linear `Done` — a three-way
disagreement no rule in the table resolves.

**Because of this the gate is NOT yet wired into `.claude/sdlc.local.md` or
`.github/workflows/repo-checks.yml`.** Wiring a check that is red on `main` would block every PR
in the repo. The script and its suite land now; the wiring lands with the answer.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `.claude/scripts/check_mirror_status.py` (new),
  `.claude/scripts/tests/test_check_mirror_status.py` (new, 35 tests),
  87 swept `docs/tasks/*.md`, 10 closed `docs/work/*.md`, this ledger + its mirror.
  NOT written, pending the STOP: the `repo` stack in `.claude/sdlc.local.md` and the
  `mirror-status` job in `.github/workflows/repo-checks.yml`.
- **Gates:** `check_mirror_status.py` exit 1 — 25 flagged, by design, pending the decision.
  `tests/test_check_mirror_status.py` 35 passed. `check_loop_parity.py` OK.
- **Commits:** <sha — message>
- **Deviations:** closed 10 stale LEDGERS as well as mirrors (the ticket says mirrors only);
  did not wire the gate into the gate lane (STOP above).
