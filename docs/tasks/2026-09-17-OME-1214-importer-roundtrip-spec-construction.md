---
id: OME-1214
linear_url: https://linear.app/openmined/issue/OME-1214/a-board-spec-change-can-break-the-importer-without-any-test-failing
status: done
type: task
priority: low
labels: [screamingface-engine]
parent: OME-1111
created: 2026-09-17
closed: 2026-09-17
---

# A board-spec change can break the importer without any test failing

The importer's emitted SnapshotSpec/BoardSpec rows were only `ast.parse`d — a renamed or
newly-required field on either dataclass kept every test green and broke weeks later as a
`TypeError` inside a generated file at the next import session. Two round-trip tests now
exec the emitted rows with the REAL dataclasses in the namespace, so the emitted kwargs
must construct the real spec — a spec change fails in its own PR. Test-only; the ticket's
optional in-importer `dataclasses.fields` guard was skipped (heavy import edge; the exec
tests already pin the contract).

Ledger: `docs/work/2026-09-17-OME-1214-importer-roundtrip-spec-construction.md`.
