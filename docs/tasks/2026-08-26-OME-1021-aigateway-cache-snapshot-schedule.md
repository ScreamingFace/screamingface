---
id: OME-1021
linear_url: https://linear.app/openmined/issue/OME-1021/snapshot-the-aigateway-response-cache-to-garage-every-friday-0500-utc
status: backlog
type: null
priority: 3
labels: [aigateway, autonomous, agentic]
created: 2026-08-26
closed: null
---

# Snapshot the aigateway response cache to Garage every Friday 05:00 UTC

The global response cache (`request_cache_entries`) holds paid-for answers that exist only
in Postgres — a lost deployment loses them. This adds a weekly archive: every Friday
05:00 UTC the gateway streams the table into the existing OME-952 snapshot format
(`.sql.gz` + manifest) and PUTs it to a Garage instance bundled in the aigateway chart,
under a dedicated bucket/prefix (`screamingface-cache-snapshots` / `cache-snapshots/…`)
that cannot collide with the Engine's artifact keys. Strictly next-Friday scheduling (no
catch-up), keep-all retention, schedule-only (no manual trigger), in-process scheduler
under the single-replica invariant.

Spec: `docs/spec/2026-08-26-OME-1021-aigateway-cache-snapshot-schedule.md` · Plan:
`docs/plan/2026-08-26-OME-1021-aigateway-cache-snapshot-schedule.md` · Ledger:
`docs/work/aigw/2026-08-26-OME-1021-cache-snapshot-schedule.md`
