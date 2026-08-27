# Complexity Baseline — apps/report-intake

(`OME-1005`, refreshed by `OME-1006`, `OME-1007`, `OME-1008`, `OME-1009`, `OME-1010`,
`OME-1011`)

Captured on 2026-08-26, against `src/` **and** `tests/` — CI runs
`ruff check` from the app root, so the whole tree is in scope and a baseline taken over
`src/` alone under-reports the high-water mark (the mistake scoreboard had to re-baseline
for).

**This app starts on the strict tier, not on a grandfathered one.** aigateway's looser
numbers are an explicitly labelled Day-1 accommodation of a codebase that already existed
when the rules arrived. A greenfield app has nothing to accommodate, so it takes the same
thresholds scoreboard and the engine are on and the numbers below show real headroom rather
than a ceiling raised to fit what was written.

Baseline produced from the app root via:

```bash
uv run ruff check . \
  --select C901,PLR0911,PLR0912,PLR0915,PLR1702 \
  --no-fix --output-format json \
  --config 'lint.mccabe.max-complexity = 1' \
  --config 'lint.pylint.max-statements = 5' \
  --config 'lint.pylint.max-branches = 3' \
  --config 'lint.pylint.max-returns = 2'
```

Each tightening PR (one rule, one ratchet at a time) should reference this file and the
`file:line` below it is reducing.

## C901 — McCabe cyclomatic complexity

- **Threshold:** `max-complexity = 8`
- **High-water:** 7, in `src/`

### Top offenders — production code (`src/`)

| Complexity | File:line |
|-----------:|-----------|
| 7 | `src/report_intake/main.py:70` (`_classify_forwarded_allow_ips`) |
| 6 | `src/report_intake/main.py:106` (`_find_forwarded_allow_ips_overlap`) |
| 4 | `src/report_intake/classification/content.py:203` (`_walk`) |
| 4 | `src/report_intake/core/body_limit.py:29` (`_declared_length`) |
| 4 | `src/report_intake/core/body_limit.py:52` (`BodyLimitMiddleware.__call__`) |
| 4 | `src/report_intake/core/body_limit.py:64` (`_while_counting`) |
| 4 | `src/report_intake/main.py:124` (`_check_forwarded_allow_ips`) |
| 4 | `src/report_intake/main.py:162` (`_check_auth_mode`) |
| 4 | `src/report_intake/reports/binding.py:50` (`_parse`) |
| 4 | `src/report_intake/reports/caps.py:82` (`structural_violation`) |
| 4 | `src/report_intake/reports/caps.py:130` (`_walk_strings`) |
| 4 | `src/report_intake/reports/caps.py:200` (`_cap_error_containers`) |
| 4 | `src/report_intake/reports/store.py:308` (`ReportStore._record`) |

### Top offenders — test code (`tests/`)

| Complexity | File:line |
|-----------:|-----------|
| 5 | `tests/unit/test_readiness.py:33` (`_registered_paths`) |
| 4 | `tests/unit/test_body_limit.py:113` |
| 4 | `tests/unit/test_local_only.py:104` (`_refused_by`) |
| 4 | `tests/unit/test_local_only.py:167` |
| 4 | `tests/unit/test_mesh_identity.py:97` |
| 4 | `tests/unit/test_body_limit.py:138` |
| 4 | `tests/unit/test_body_limit.py:160` |

## PLR0915 — Too many statements

- **Threshold:** `max-statements = 26`
- **High-water:** 23, in `src/` — `create_app`, and by construction: every item's wiring lands
  there as two or three more lines.

| Statements | File:line |
|-----------:|-----------|
| 23 | `src/report_intake/main.py:276` (`create_app`) |
| 18 | `src/report_intake/main.py:70` (`_classify_forwarded_allow_ips`) |
| 14 | `src/report_intake/main.py:212` (`_lifespan`) |
| 13 | `tests/unit/test_logs.py:23` |
| 13 | `src/report_intake/routes/reports.py:60` (`submit_report`) |
| 12 | `src/report_intake/reports/store.py:342` (`ReportStore._record_delivery`) |
| 11 | `src/report_intake/identity/turnstile.py:168` (`enforce`) |
| 11 | `tests/unit/test_body_limit.py:160` |
| 11 | `tests/unit/test_retry_queue.py:110` |
| 10 | `src/report_intake/core/body_limit.py:64` |
| 10 | `tests/unit/test_body_limit.py:113` |
| 10 | `tests/unit/test_body_limit.py:138` |
| 10 | `tests/unit/test_cli.py:12` |
| 10 | `tests/unit/test_readiness.py:33` |
|  9 | `src/report_intake/classification/content.py:203` |
|  9 | `src/report_intake/core/body_limit.py:52` |
|  9 | `src/report_intake/logs.py:39` |
|  9 | `src/report_intake/main.py:120` |
|  9 | `src/report_intake/reports/binding.py:50` |
|  9 | `src/report_intake/reports/caps.py:130` |
|  9 | `src/report_intake/reports/caps.py:200` |
|  9 | `tests/unit/test_ticket_render.py:140` |

## PLR0912 — Too many branches

- **Threshold:** `max-branches = 7`
- **High-water:** 6, in `src/`

| Branches | File:line |
|---------:|-----------|
| 6 | `src/report_intake/main.py:70` |
| 5 | `src/report_intake/main.py:106` |
| 4 | `src/report_intake/core/body_limit.py:52` |
| 4 | `src/report_intake/reports/caps.py:130` |
| 4 | `tests/unit/test_readiness.py:33` |

## PLR0911 — Too many return statements

- **Threshold:** `max-returns = 3`
- **High-water:** 3, in `src/`

| Returns | File:line |
|--------:|-----------|
| 3 | `src/report_intake/classification/content.py:222` (`_finding`) |
| 3 | `src/report_intake/classification/content.py:245` (`_oversized_leaf`) |
| 3 | `src/report_intake/config.py:30` (`normalize_database_url`) |
| 3 | `src/report_intake/core/local_only.py:63` (`_is_loopback_host`) |
| 3 | `src/report_intake/core/local_only.py:82` (`_is_loopback_client`) |
| 3 | `src/report_intake/identity/gate.py:35` (`admit`) |
| 3 | `src/report_intake/identity/mesh_identity.py:49` (`peer_in_networks`) |
| 3 | `src/report_intake/identity/mesh_identity.py:78` (`mesh_caller_email`) |
| 3 | `src/report_intake/identity/rate_limit.py:101` (`TokenBucketLimiter.check`) |
| 3 | `src/report_intake/identity/rate_limit.py:154` (`rate_limit_key`) |
| 3 | `src/report_intake/core/body_limit.py:29` |
| 3 | `src/report_intake/delivery/dispatch.py:84` (`TicketDispatcher._attempt`) |
| 3 | `src/report_intake/main.py:106` |
| 3 | `src/report_intake/reports/caps.py:82` |
| 3 | `src/report_intake/reports/caps.py:152` |
| 3 | `src/report_intake/reports/retry.py:224` (`RetryQueue._schedule`) |
| 3 | `src/report_intake/reports/store.py:308` (`ReportStore._record`) |
| 3 | `src/report_intake/reports/store.py:414` (`ReportStore._replay`) |

## PLR1702 — Too many nested blocks (no tunable)

No violations. The rule is preview-only in current ruff (`ruff check` prints
`Selection PLR1702 has no effect because preview is not enabled` — the same warning the
other stacks carry), and it is kept in `select` so violations surface the day it promotes.

## Tightening roadmap (one PR per ratchet)

The high-water marks above all sit at or under the thresholds with room to spare, so the
first ratchet here is a matter of choosing, not of paying down debt. `OME-1006` roughly
tripled the tree and moved none of the four headline numbers, `OME-1007` added the classifier
without moving them either, `OME-1008` added the store, the migration, and the lifespan and
still moved none, `OME-1009` added the delivery port, the renderer, the registry and the
dispatcher and moved none, `OME-1010` added the retry queue, its claim and its schedule and
moved none, and `OME-1011` added the whole identity package — mesh identity, the rate limiter,
the bot gate, the loopback guard — and moved none of C901, PLR0911 or PLR0912 either. That is
the evidence that the strict tier is affordable here rather than merely aspirational: six items
and the only number that has moved at all is the composition root's.

`create_app`: 16 → 18 (`OME-1009`) → 20 (`OME-1010`) → 23 (`OME-1011`), three under its
threshold and by construction, because every item's wiring lands there as two or three more
lines. `OME-1011` kept it to three by putting the whole middleware stack in `_install_middleware`
rather than inline, which is also where the add-order comment belongs. `_lifespan` moved 11 → 14
for the two seams the identity work owns and the verifier it has to close; `OME-1010` had
previously taken two statements OFF it (13 → 11) by moving the cancel-and-await into `_stop`.

`max-returns = 3` did cost something real, twice: `ReportStore._replay` reads its "no key"
guard as a conditional expression rather than an early return (a better comment anyway — a
lookup on `idempotency_key=None` matches every keyless row), and `TicketDispatcher` splits
`dispatch` from `_attempt` rather than answering four ways in one function. Both splits are
the shape the rule was asking for.

1. PLR0911 `max-returns`: already at the high-water mark (3); the next lower value would
   require restructuring `_find_forwarded_allow_ips_overlap`, `_declared_length`,
   `structural_violation`, `_cap_string`, and the classifier's `_finding` / `_oversized_leaf`
   — each of which is a three-way answer (this kind, that kind, neither) that a two-return
   rewrite turns into a flag variable.
2. PLR0912 `max-branches`: 7 → 6 is reachable today.
3. C901 `max-complexity`: 8 → 7 is reachable today.
4. PLR0915 `max-statements`: 26 → 24 is what is left, because `create_app` is now 23. The
   earlier suggestion of 22 is no longer reachable without splitting the composition root, and
   splitting it is the wrong trade: `create_app` reads top to bottom as "what this service is
   made of", and hiding a third of it behind helpers to satisfy a threshold nobody has hit
   makes the wiring harder to audit, which is the thing the wiring is for. `OME-1012` adds no
   application wiring, so 24 should hold.

**Do not ratchet a threshold below a number this file records without reducing the named
offender in the same PR** — the two move together, or the next contributor discovers the
rule by having their unrelated change rejected.
