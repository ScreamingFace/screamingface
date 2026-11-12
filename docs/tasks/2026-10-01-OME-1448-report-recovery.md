---
id: OME-1448
linear_url: https://linear.app/openmined/issue/OME-1448/a-finished-evaluation-is-lost-when-the-notebook-runs-out-of-memory
status: done
type: feature
priority: high
labels: [client-sf, agentic, design-session]
parent: OME-1294
created: 2026-10-01
closed: 2026-11-04
---

# A finished evaluation is lost when the notebook runs out of memory while building its report

Design umbrella under E5 (OME-1294). On 2026-10-01 a full ContractEval run (11 Candidates, 4,182 Cases, about $2,600) crashed a 16 GB notebook while the SDK built the Report. The results were saved only by hand from the local Engine's temp folder. The ticket listed four options: A (recovery record + recover by run id), B (stream the result to disk, decode Case by Case), C (stop repeating the prompt per Case), D (stream the export).

The first PR, #1211 (branch `OME-1448-report-recovery`), was closed. Its work was split out of #1156 into these slices, all merged:

| Option / fault | PR | Squash commit | Ticket |
| -- | -- | -- | -- |
| D · streamed, atomic `Report.export()` | #1241 | `af1a10024` | OME-1486 |
| A + B · completion record before download, disk-backed Cases, `sf.reports.list/get/delete` | #1269 | `e7833e35c` | OME-1503 |
| B · compact accounting without Case payloads | #1345 | `4fbdfdce2` | OME-1570 |
| B · bounded notebook rendering, 25-row pages | #1347 | `8e0c0a298` | OME-1571 |
| A · crash notice with `sf.reports.get(...)`, run-id lookup | #1348 | `90392e95e` | OME-1572 |
| F3 · local artifacts in `<data_dir>/artifacts`, not `$TMPDIR` | #1217 | `05ed45b09` | OME-1454 |

Not done, and known limits (also in the Linear close comment):

- Option C: each Case still carries the full prompt in `input`. It rides the result-schema v2 work in OME-1033.
- No `screamingface recover` CLI. Recovery is `sf.reports.get(...)`.
- An expired Engine artifact gives a general message, not a specific "expired" message.
- Recovery does not help if the process dies before the SDK saves the completion record.
- The original 16 GB / 11-Candidate failure was not run again. All evidence is synthetic.

Closed in Linear on 2026-11-04.
