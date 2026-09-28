---
ticket: OME-1182
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-1182 — Automate the phase acceptance check against the deployed stack

## Intent

`OME-1118`'s acceptance was a SigNoz query, and it was run by hand: drive a run against the
deployed engine, read the `trace_id` off the report, poll the SigNoz API, eyeball whether lines
came back from both namespaces. It passed — 28 and 31 lines across `sf-fusion` and `sf-aigw` —
but the procedure lives only in a chat transcript, so Phase 2 would re-invent it.

One command that performs a phase's deployed acceptance and exits non-zero when it does not
hold.

## Design decisions

**D1 — the tool triggers its own run.** This is the whole reason it is a tool and not a query.
During `OME-940` a real diagnosis went wrong because `job_name=` was absent from the deployed
logs: the conclusion drawn was "not deployed", and the truth was "no run has happened since the
merge". Triggering removes that ambiguity **by construction** — if the tool drove the run, then
absence is a real absence.

**D2 — three outcomes, not two: PASS / FAIL / BLOCKED.** `OME-1106`'s review found the
opposite mistake twice, where `UNKNOWN` did not block and the script printed READY for a lane
that could not run. "No SigNoz token", "no Access session", "no trace id" are not failures of
the phase — they are failures to check, and reporting them as FAIL would send someone hunting a
regression that does not exist. All three exit non-zero; only their reason differs.

**D3 — no signal may pass vacuously.** Every assertion requires a NON-EMPTY result before
comparing anything. Ladder rung 2 once reported `XPASS(strict)` because `set() == set()` was
true with both sides empty; the same shape here would report a phase green while nothing was
correlated.

**D4 — assert on tokens unique to the change.** Searching `run scheduled` returns the
pre-existing `rest/routes.py` line as well as `OME-940`'s adapter line, and that nearly produced
a false positive. Signals therefore key on `trace_id=` and on the specific logger, never on a
phrase that predates the work.

**D5 — the phase's signal set is DATA, not code.** A table keyed by phase number, so Phase 2
adds rows rather than editing control flow. Phase 2 asserts spans rather than log lines, so its
`kind` differs — that is why a signal carries a query strategy and not just a substring.

**D6 — polling, with a stated bound.** Ingestion is not instant; a single immediate query
would produce a flaky FAIL. Poll to a deadline and report the wait, so a slow ingest reads as
slow rather than broken.

## Out of scope

**A CI job.** This needs a Cloudflare Access session and a live deployment, so it is an
operator command rather than a merge gate. The local ladder (`test_correlation_chain.py`)
remains the gate that holds. Whether `e2e/failor/` should be gated at all is `OME-1106`'s open
question, not this one's.

## Planned changes

- `e2e/failor/verify_phase.py` (new) — the tool.
- `e2e/failor/README.md` — a pointer, if one exists; otherwise skip.

## Test plan

The tool's own correctness is checked by forcing each outcome, because a validator that cannot
fail is the defect this unit exists to avoid:

- **PASS** against the deployed stack for Phase 1 — the real acceptance.
- **FAIL** for a trace id that does not exist (a well-formed id with no lines) — proves the
  assertions are not vacuous.
- **BLOCKED** with no `SIGNOZ_TOKEN` — proves "could not check" is distinguishable from FAIL.
- **BLOCKED** when the run yields no trace id.
- A namespace that shipped no lines is named individually, not folded into a single failure.

## Acceptance

- `verify_phase.py --phase 1` exits 0 against the deployed stack and prints a per-signal table.
- Each non-pass path exits non-zero with its true reason.
- Phase 2 can be added as table rows.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `e2e/failor/verify_phase.py` (new), ledger + mirror. No README existed to
  point at, so none was edited.
- **Commits:** `feat(e2e): automate the phase acceptance check against the deployed stack`
  (sha at squash-merge).
- **Gates:** no stack gate covers `e2e/failor/` (it is outside every uv project — the gap
  `OME-1106`'s review raised). `ruff check` + `ruff format --check` clean. The tool was
  verified by **forcing every outcome against the real deployed stack**:

  | scenario | expected | got |
  |---|---|---|
  | real trace id | PASS, exit 0 | PASS — `sf-fusion=11`, `sf-aigw=17`, 28 lines |
  | fabricated trace id | FAIL, exit 1 | FAIL — **4 of 4** signals absent |
  | `SIGNOZ_TOKEN` unset | BLOCKED, exit 2 | BLOCKED, names the token |
  | undefined phase | BLOCKED, exit 2 | BLOCKED, lists defined phases |
  | malformed trace id | BLOCKED, exit 2 | BLOCKED, names the shape |
  | trigger with no Access session | BLOCKED, exit 2 | BLOCKED, names the auth timeout |

- **Deviations:**
  - **The first version of the `gateway_call_id` signal passed for a FABRICATED trace id**, and
    that is the most important thing in this ledger. It searched for `gateway_call_id=` alone,
    so it matched some unrelated line and reported 3-of-4 rather than 4-of-4 on a bogus id —
    exactly the weakness ladder rung 4b's own docstring warns about ("a log full of unrelated
    hex would satisfy the weaker check while joining nothing"). I codified that principle in
    the ladder and then violated it in the tool built to enforce it. `Signal.contains` became a
    TUPLE whose terms must all appear on the SAME line, and a fabricated id now fails all four.
  - **My verification harness was itself unable to fail.** The first pass piped the tool through
    `tail`, so `$?` was `tail`'s status and every scenario printed `exit=0` — including the ones
    that were working correctly. Re-run capturing the real status. Worth recording because it is
    the same defect class the tool exists to prevent, one level up.
  - **BLOCKED now prints the reason that HAPPENED, not a menu.** An earlier version always
    suggested `cloudflared access login` — and printed it immediately after a login that had
    just succeeded, while the real failure was an unreachable benchmark catalog. A remedy that
    does not match the cause sends the reader to fix something that is not broken.
  - **The trigger path is verified only up to the auth boundary.** Completing Cloudflare Access
    needs an interactive browser step, so an unattended run reaches `AuthenticationError` and
    correctly reports BLOCKED. The assertion logic is fully verified through `--trace-id`
    against two real deployed runs.
  - `REPO_ROOT` is defined and currently unused; kept because the phase table will need to
    resolve repo-relative fixtures when Phase 2 rows are added. Flagged rather than silently
    left.
