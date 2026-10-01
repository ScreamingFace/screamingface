# OME-1448: Recover a finished Evaluation, and export with bounded memory

**Ticket:** [OME-1448](https://linear.app/openmined/issue/OME-1448) · **Epic:** OME-1294 (E5)
**Status:** spec; open questions resolved 2026-10-01 · **Branch:** `OME-1448-report-recovery` · **Date:** 2026-10-01

## 1. Summary

On 2026-10-01, a ContractEval run (11 Candidates, 4,182 Cases, about $2,600) finished on the
Engine, but the notebook ran out of memory while the SDK built the Report. Nothing told the
researcher that the results were still on disk. On the hosted stack, nothing recorded the
artifact ids, so the researcher could not recover the results at all.

This spec makes every finished Evaluation recoverable, on the local and the hosted stack, and
makes export and recovery use bounded memory. It contains:

- **A (recovery):** the SDK writes a small record for each Evaluation, and for each finished run
  before it downloads the result. One call, `sf.recover(id)` or
  `screamingface recover <id> --to report.json`, rebuilds the same Report or the same file.
- **D (export):** `Report.export()` streams one Candidate at a time, with the same bytes.
- **Local durable folder:** `screamingface up` keeps spilled results in
  `~/.screamingface/artifacts` instead of `$TMPDIR`, so a reboot does not delete them.

Options B (streaming decode) and C (no per-Case prompt, schema v2) are later work. `[stated ans:Q1]`

All changes are in `packages/screamingface`. The Engine and AIGateway do not change, so no
sub-issues are needed.

## 2. Subsystems and ownership

| Subsystem | Code | Owner |
|---|---|---|
| Recovery store (port + filesystem adapter) | `_core/ports.py`, new `_recovery/` | SDK |
| Record hook in the transports and the runner | `_engine/transport.py`, `_evaluation/runner.py`, `_evaluation/url4.py` | SDK |
| Recover service, `sf.recover`, `sf.recoverable`, CLI | new `_recovery/service.py`, `_default_client.py`, `client.py`, `_runtime/cli.py` | SDK |
| Streaming writer, `Report.export` | `report.py` | SDK |
| Local artifact folder | `_runtime/config.py`, `_runtime/server.py` | SDK |

## 3. Reading order

1. `erd.md`: entities, layout, state machine.
2. `prd/recovery-store.md` (component), then `prd/report-json-writer.md` (component).
3. `prd/record-evaluation.md`, then `prd/recover-evaluation.md`: the P0 flows.
4. `prd/recovery-notice.md`, `prd/export-report.md`, `prd/local-durable-artifacts.md`: P1.
5. `contracts.md`, then `test-plan.md`.

| PRD | Kind | Priority | Scenarios | TDD rows |
|---|---|---|---|---|
| `prd/recovery-store.md` | component | P0 | 18 | 19 |
| `prd/report-json-writer.md` | component | P0 | 7 | 7 |
| `prd/record-evaluation.md` | flow | P0 | 14 | 15 |
| `prd/recover-evaluation.md` | flow | P0 | 21 | 22 |
| `prd/recovery-notice.md` | flow | P1 | 11 | 11 |
| `prd/export-report.md` | flow | P1 | 8 | 8 |
| `prd/local-durable-artifacts.md` | flow | P1 | 8 | 8 |

## 4. Interview ledger

| ID | Question | Answer |
|---|---|---|
| Q1 | Which options to fully specify | "A + D + local dir" (recommended). B and C are later work only. |
| Q2 | How recover relates to the blocked E5 runs API | "Standalone recover" (recommended): `sf.recover(...)` plus a `screamingface recover` CLI that E5 can wrap later. |
| Q3 | What one recover call returns | "Whole evaluation" (recommended): the same multi-Candidate Report. Single runs stay addressable. |
| Q4 | How long to keep records | "Until recovered or expired" (recommended): delete after a successful recover, or when the server copy is confirmed gone. |
| Q5 | How the researcher learns of a recoverable run | "Notice on next start" (recommended), plus `screamingface recover --list`. |
| Q6 | Should the SDK keep its own copy of large results | "Pointer only" (recommended). |
| Q7 | Cover Candidates still running at the crash | "Finished runs only" (recommended). Missing ones are named as failed, as in a partial Report. |
| Q8 | Hosted bucket retention | "SDK handles 404 only" (recommended). Infra retention is a separate dependency. |
| Q9 | Memory during recovery | "Add recover-to-file" (recommended): bounded by one Candidate; in-memory recover stays. |
| Q10 | The record after a normal success | "Keep quietly" (recommended): `delivered`, no notice, deleted when the server copy is gone or after 7 days. |
| Q11 | Local stack down at recover time | "Clear error" (recommended). Start nothing. |
| Q12 | Serialize large downloads during a normal run | "Keep parallel". **You picked against the recommendation**; the spec keeps today's parallel downloads. |
| Q13 | OQ-1: after a successful recover, delete the record (Q4) or keep it as `delivered` (Q10's rule)? | "Answer 10 is the right now": keep it as `delivered`, and restart the 7-day clock. |
| Q14 | OQ-2: hosted bucket retention | "ok": a separate infra ticket, outside this unit. |
| Q15 | OQ-3: confirm with the E5 owner that `sf.recover` does not conflict with the runs API | "it doesn't just do it": no conflict, so proceed without a confirmation. |
| Q16 | File the OQ-2 infra ticket now? | "let`s post pone it for now": not filed. |

Note on Q9: the option text said that recover-to-file "adds ijson as a direct dependency". The
spec meets the same bound (one Candidate) by staging each artifact to a file and decoding it with
`json.load`, so it adds no dependency. `[proposed]`

## 5. Global assumptions

- The SDK targets macOS and Linux. Windows is not tested (`test-plan.md` §7). `[proposed]`
- `<data_dir>` is on a local disk with normal POSIX `rename` semantics. `[proposed]`
- The Engine's artifact route and the capability-token rules stay as they are today. `[existing apps/screamingface-engine/src/screamingface_engine/rest/artifacts.py:97]`

## 6. Ticket corrections found while writing this spec

1. The ticket's "Don't regress" list says "the 1 MiB inline cap (OME-949)", and recovery step 1
   says "over 1 MiB". OME-949 set the default to **512 KiB** (`job_env.py:430`). This spec keeps
   512 KiB.
2. Option A's pointer fields (engine URL, Candidate name, file id, size, sha256) cannot rebuild
   "the same Report". The Report also needs the Candidate's URL4 and answer seed, and the run
   metadata (run id, trace id, times, usage, cache savings, client version, cache hits). The ERD
   stores these.
3. Option A writes "at the terminal frame". The record must also exist before the download,
   which is the first memory peak (8 parallel downloads, about 600 MB each). The spec places the
   write between the terminal frame and `_materialize_*`.
4. A + D alone do not make the incident recoverable on the same 16 GB laptop, because an
   in-memory recovery builds the same Report. That is why recover-to-file exists (Q9).

## 7. Deferred and open questions

All three questions are resolved (Q13–Q15 above). The only deferred item is OQ-2, the hosted
bucket lifecycle. It goes to a separate infra ticket, outside this unit. `[stated ans:Q14]`
On 2026-10-01 you postponed filing that ticket. Nothing is filed for now. `[stated ans:Q16]`

## 8. Next steps

1. Plan: `docs/plan/2026-10-01-OME-1448-report-recovery.md`.
2. Code starts only after you approve the plan in plain words.
