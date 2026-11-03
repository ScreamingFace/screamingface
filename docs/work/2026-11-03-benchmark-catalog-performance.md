---
ticket: unfiled
stack: scoreboard
status: done
started: 2026-11-03
finished: 2026-11-03
---

# Benchmark catalog performance measurements

## Intent

Compare today's homepage with the uncached summary implementation. Distinguish local
application measurements from network models and unknown production database costs.

## Method

Captured three normal anonymous production homepage loads with Chrome on 2026-11-03.
Saved the public catalog and top=1 responses: 87 registered benchmarks, 86 listed,
21 top score rows. Seeded a disposable local PostgreSQL 15 database with those public
rows and baselines. Both homepage versions used this SAME database and local API.
Old HTML/main.js came from base commit ffdc7e93f; the new version includes the final
bulk privacy recheck. No application or response caching, no production writes.

Browser comparisons: 5 runs per variant/profile. Metric is first API request start
to first usable cards, not navigation or page-load event. The old version waits for
all 86 boards; the new version displays 9 of 21 scored cards. Both are usable at the
same nine-card milestone. Search/filter then require no more requests.

## Results

Production navigation-to-cards: 2255, 1816, 1776 ms (three samples, not percentiles).
Every load made 87 API requests. Local browser results:

| Profile | Old median (range), ms | Summary median (range), ms |
| --- | ---: | ---: |
| Actual local PostgreSQL + loopback | 126 (123–165) | 11 (9–32) |
| Same app, 150 ms added per API request | 425 (419–454) | 162 (159–166) |
| Recorded-response delay model | 1825 (1825–1831) | 307 (301–310) |

API requests: 87 → 1. Decoded local API body bytes: 452717 → 78453 (about 83% less).
These are decoded bytes; do not compare directly with production's compressed sizes.
Backend reads: two fixed queries (grouped scores + final bulk visibility check),
independent of the number of benchmarks. No database migration or cache.

The recorded-response model pads old requests to observed per-endpoint durations.
The summary assumes the observed catalog delay plus actual local endpoint work. This
reproduces the OLD visible delay by construction; the 307 ms result is a modeled
scenario, NOT a measured production prediction or an independently discovered cause
of server latency. The same 150 ms/request experiment is the controlled comparison.

## Synthetic data growth

Actual local HTTP endpoint timings, 12 repetitions per dataset. Added lower-ranked
synthetic submissions to the same 21 scored boards. Checked every summary score
against all detailed top=1 responses on every repetition. Restored the original
21-row fixture afterward.

| Total score rows | Summary median response, ms |
| ---: | ---: |
| 21 public top rows | 4.75 |
| 2100 (synthetic depth) | 5.30 |
| 21000 (synthetic depth) | 27.17 |

These include local HTTP overhead and warm database buffers. Unknown: production
history depth/distribution, concurrent traffic, database hardware, pool pressure,
network topology and query plans. No claim of production-wide latency or p95.

## Reproduction artifacts

Versioned directory: docs/spec/benchmark-catalog-summary/evidence/.
capture.cjs saves live.json.gz;
seed.py initializes an explicitly disposable local database; compare.cjs saves
comparison.json; server_timings.py saves server-timings.json; smoke.cjs saves browser
screenshots and smoke.json. README there gives commands. The compressed public snapshot and generated screenshots are review evidence,
not shipped app assets. Uncompressed working artifacts also remain in output/performance/.

## Acceptance and outcome

- Baseline request pattern and rough visible delay reproduced.
- Actual uncached implementation measured against the same fixture and fixed latency.
- Score parity held throughout growth runs; no synthetic rows left in fixture.
- PostgreSQL 15 local; PostgreSQL 17 remains the CI verification target.
- Production measurement after deployment is still required to establish real speedup.
