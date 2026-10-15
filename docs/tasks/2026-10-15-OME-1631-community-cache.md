# OME-1631 — Serve the community cache in pages and load them into a local SQLite gateway

Status: In Review
Labels: aigateway, agentic, autonomous
Parent: OME-1311
Linear: https://linear.app/openmined/issue/OME-1631

AIGateway half of epic OME-1311 (PR 1 of 3). `GET /v1/cache/entries` pages the shareable rows of
the global request cache to any signed-in account as NDJSON (header, rows, trailer with the next
cursor), in write order `(updated_at, key_hash)` on migration 0015's index, 100 rows per query,
with an optional exact `model` filter and `count=true` for progress. `sqlite_loader` checks
revisions and loads each page into the local SQLite cache in one transaction, keeping local rows.
Draft PR; the Engine proxy (PR 2) and `sf.cache.pull_from_remote` (PR 3) follow under the epic.

Spec: ../spec/2026-10-15-community-cache.md
Plan: ../plan/2026-10-15-community-cache.md
Ledger: ../work/2026-10-15-community-cache.md
