---
id: OME-1452
linear_url: https://linear.app/openmined/issue/OME-1452/size-the-scoreboard-db-pool-explicitly-so-readyz-cannot-flap-under
status: done
type: fix
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-935
created: 2026-10-01
closed: 2026-10-05
---

# Size the scoreboard DB pool explicitly so /readyz cannot flap under load

`/readyz` (OME-944) ran its 2 s-capped `SELECT 1` on the request pool, whose size was Tortoise's
silent default (verified: min 1 / max 5 in tortoise-orm 1.1.8, overriding asyncpg's 10 / 10). A
load spike holding every pooled connection would make the probe time out on every replica at once.
The probe now runs on a reserved one-connection pool no model uses, and the request pool is sized
by `SCOREBOARD_DB_POOL_MINSIZE` / `SCOREBOARD_DB_POOL_MAXSIZE` (chart `config.dbPoolMinsize` /
`dbPoolMaxsize`, 1 / 5 — no capacity change).

- 2026-10-01: PR opened (branch `bershadsky/ome-1452-…`, ledger
  `docs/work/2026-10-01-scoreboard-db-pool-readiness.md`).
