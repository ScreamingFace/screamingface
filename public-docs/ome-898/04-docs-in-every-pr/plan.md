---
title: "Documentation as part of every PR: implementation plan"
ticket: OME-898 (child 4, not yet filed)
spec: ./spec.md
status: draft
date: 2026-09-17
---

# Documentation as part of every PR: implementation plan

Builds the three-layer mechanism in `spec.md`. Only layer 2, the CI check, is buildable now;
layers 1 and 3 both need child 01 published, and layer 1 also needs child 03's routing.

## Steps

**1. The symbol-to-page table.** `symbol-page-map.md`. `sfClientReferenceNavigation` groups
pages by class family, not by exact `__all__` name: its "Candidates" group alone spans five
separate exports (`Recipe`, `Model`, `Fusion`, `Pipeline`, `Url4`), each with its own page.
55 of the 58 `__all__` names map to a page; `__version__`, `OperationAccounting`, and
`OperationCache` have none.

**2. The check script.** `scripts/check_docs_sync.py`. Parses `__init__.py`'s `__all__` and
its import statements with `ast`, rather than a directory-naming convention, since two real
public names' backing files (`_default_client.py`, `_ui/connections.py`) sit under an
underscore prefix. A name counts as changed if it is new in `__all__`, removed from it, or
its backing file changed.

**3. The CI job.** `docs-sync-check.yml`, its own workflow rather than a job in
`public-docs-tests.yml`, which triggers only on `public-docs/**` and would never run for a
PR that changes only the Python side. Triggers on either side of the pair, diffs against the
PR's base SHA via `fetch-depth: 0`, passes the SHA through an environment variable rather
than interpolating it into the shell command. Live at `.github/workflows/docs-sync-check.yml`.

## Verification

- `dd51ea81` ("retain operation accounting") added `OperationAccounting` and
  `OperationCache` to `__all__` with no docs page; the check fails, naming both. Neither has
  a page today, months later.
- The same commit shows the file-granularity limitation: ten other names sharing
  `report.py` get flagged too, though the commit's actual change did not touch them.
  Recorded in `spec.md`.
- `2b47ae3c` touches only an underscore-prefixed file and unrelated `apps/scoreboard` code;
  the check reports zero changed symbols.
- All 58 `__all__` names are covered by the table; the three with no page are named
  exceptions in `symbol-page-map.md`, not silent gaps.

## Later

**Layer 1**, once child 01 ships: a routing rule in `.claude/` (child 03's territory) that
invokes the `writing-docs` skill on a public-surface change, before a PR opens.

**Layer 3**, once child 01 ships: a bot identity with write access to open a follow-up PR
against `public-docs/`, using the same skill to draft content, triggered when a PR merges
without the layer-2 check having passed.

## Sequence

```
1 symbol table -> 2 check script -> 3 CI job
                                    (ships independently)

child 01 publishes -+-> layer 1 (needs child 03 too)
                     +-> layer 3
```
