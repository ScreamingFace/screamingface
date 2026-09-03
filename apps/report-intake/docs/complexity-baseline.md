# Complexity Baseline — apps/report-intake

(`OME-1005`, refreshed by `OME-1006`, `OME-1007`, `OME-1008`, `OME-1009`, `OME-1010`,
`OME-1011`, and `OME-1009`'s two follow-ups — `LinearSink`, then the `queue` console)

Captured on 2026-08-27, against `src/` **and** `tests/` — CI runs
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
| 5 | `src/report_intake/delivery/linear_sink.py:208` (`_raise_for_status`) |
| 5 | `src/report_intake/reports/caps.py:211` (`_cap_error_containers`) |
| 4 | `src/report_intake/classification/content.py:214` (`_walk`) |
| 4 | `src/report_intake/core/body_limit.py:29` (`_declared_length`) |
| 4 | `src/report_intake/core/body_limit.py:52` (`BodyLimitMiddleware.__call__`) |
| 4 | `src/report_intake/core/body_limit.py:64` (`BodyLimitMiddleware._while_counting`) |
| 4 | `src/report_intake/identity/mesh_identity.py:49` (`peer_in_networks`) |
| 4 | `src/report_intake/identity/rate_limit.py:154` (`rate_limit_key`) |
| 4 | `src/report_intake/identity/turnstile.py:168` (`enforce`) |
| 4 | `src/report_intake/main.py:124` (`_check_forwarded_allow_ips`) |
| 4 | `src/report_intake/main.py:162` (`_check_auth_mode`) |
| 4 | `src/report_intake/queue_cli.py:181` (`_print_queue`) |
| 4 | `src/report_intake/queue_cli.py:192` (`_print_ticket`) |
| 4 | `src/report_intake/reports/binding.py:50` (`_parse`) |
| 4 | `src/report_intake/reports/caps.py:93` (`structural_violation`) |
| 4 | `src/report_intake/reports/caps.py:141` (`_walk_strings`) |
| 4 | `src/report_intake/reports/caps.py:227` (`_cap_object`) |
| 4 | `src/report_intake/reports/store.py:429` (`ReportStore._record`) |

### Top offenders — test code (`tests/`)

| Complexity | File:line |
|-----------:|-----------|
| 5 | `tests/unit/test_readiness.py:33` (`_registered_paths`) |
| 4 | `tests/unit/test_body_limit.py:113` (`test_a_client_that_disconnects_mid_body_is_not_handed_on_as_a_complete_request`) |
| 4 | `tests/unit/test_body_limit.py:138` (`test_a_replayed_body_reports_the_stream_closed_once_it_is_delivered`) |
| 4 | `tests/unit/test_body_limit.py:160` (`test_a_websocket_scope_is_passed_straight_through`) |
| 4 | `tests/unit/test_local_only.py:104` (`_refused_by`) |
| 4 | `tests/unit/test_local_only.py:167` (`test_a_websocket_scope_is_passed_straight_through`) |
| 4 | `tests/unit/test_mesh_identity.py:97` (`test_the_peer_check_answers_before_the_header_is_read`) |

## PLR0915 — Too many statements

- **Threshold:** `max-statements = 26`
- **High-water:** 24, in `src/` — `create_app`, and by construction: every item's wiring lands
  there as two or three more lines.

| Statements | File:line |
|-----------:|-----------|
| 24 | `src/report_intake/main.py:308` (`create_app`) |
| 18 | `src/report_intake/main.py:70` (`_classify_forwarded_allow_ips`) |
| 16 | `src/report_intake/cli.py:50` (`_parser`) |
| 15 | `src/report_intake/main.py:240` (`_lifespan`) |
| 14 | `src/report_intake/reports/caps.py:227` (`_cap_object`) |
| 13 | `src/report_intake/routes/reports.py:73` (`submit_report`) |
| 13 | `tests/unit/test_logs.py:23` (`app_logger`) |
| 12 | `src/report_intake/queue_cli.py:192` (`_print_ticket`) |
| 12 | `src/report_intake/reports/store.py:463` (`ReportStore._record_delivery`) |
| 12 | `tests/unit/test_cli.py:13` (`test_the_entrypoint_serves_the_app_on_the_configured_address`) |
| 11 | `src/report_intake/identity/turnstile.py:168` (`enforce`) |
| 11 | `tests/unit/test_body_limit.py:160` (`test_a_websocket_scope_is_passed_straight_through`) |
| 11 | `tests/unit/test_linear_sink.py:122` (`_capturing`) |
| 11 | `tests/unit/test_report_store.py:450` (`test_awaiting_triage_returns_the_queued_rows_and_nothing_else`) |
| 11 | `tests/unit/test_retry_queue.py:110` (`_capturing`) |
| 10 | `src/report_intake/core/body_limit.py:64` (`BodyLimitMiddleware._while_counting`) |
| 10 | `src/report_intake/reports/caps.py:211` (`_cap_error_containers`) |
| 10 | `tests/unit/test_body_limit.py:113` (`test_a_client_that_disconnects_mid_body_is_not_handed_on_as_a_complete_request`) |
| 10 | `tests/unit/test_body_limit.py:138` (`test_a_replayed_body_reports_the_stream_closed_once_it_is_delivered`) |
| 10 | `tests/unit/test_local_only.py:167` (`test_a_websocket_scope_is_passed_straight_through`) |
| 10 | `tests/unit/test_queue_console.py:65` (`_seed`) |
| 10 | `tests/unit/test_readiness.py:33` (`_registered_paths`) |
| 9 | `src/report_intake/classification/content.py:214` (`_walk`) |
| 9 | `src/report_intake/core/body_limit.py:52` (`BodyLimitMiddleware.__call__`) |
| 9 | `src/report_intake/delivery/linear_sink.py:208` (`_raise_for_status`) |
| 9 | `src/report_intake/delivery/linear_sink.py:280` (`_delivered`) |
| 9 | `src/report_intake/identity/gate.py:89` (`_spend_anonymous_budget`) |
| 9 | `src/report_intake/logs.py:39` (`configure`) |
| 9 | `src/report_intake/main.py:124` (`_check_forwarded_allow_ips`) |
| 9 | `src/report_intake/reports/binding.py:50` (`_parse`) |
| 9 | `src/report_intake/reports/caps.py:141` (`_walk_strings`) |
| 9 | `tests/unit/test_auth_gate.py:82` (`test_a_forged_identity_header_from_outside_the_mesh_never_reaches_the_report`) |
| 9 | `tests/unit/test_linear_sink.py:431` (`test_one_client_serves_every_report_rather_than_one_per_delivery`) |
| 9 | `tests/unit/test_ticket_render.py:140` (`test_a_credential_dropped_into_an_extension_point_is_excluded_by_name_not_by_pattern`) |
| 9 | `tests/unit/test_ticket_render.py:225` (`test_a_correlation_id_cannot_forge_a_section_of_its_own`) |

## PLR0912 — Too many branches

- **Threshold:** `max-branches = 7`
- **High-water:** 6, in `src/`

| Branches | File:line |
|---------:|-----------|
| 6 | `src/report_intake/main.py:70` (`_classify_forwarded_allow_ips`) |
| 5 | `src/report_intake/main.py:106` (`_find_forwarded_allow_ips_overlap`) |
| 4 | `src/report_intake/core/body_limit.py:52` (`BodyLimitMiddleware.__call__`) |
| 4 | `src/report_intake/delivery/linear_sink.py:208` (`_raise_for_status`) |
| 4 | `src/report_intake/reports/caps.py:141` (`_walk_strings`) |
| 4 | `src/report_intake/reports/caps.py:211` (`_cap_error_containers`) |
| 4 | `tests/unit/test_readiness.py:33` (`_registered_paths`) |

## PLR0911 — Too many return statements

- **Threshold:** `max-returns = 3`
- **High-water:** 3, in `src/`

| Returns | File:line |
|--------:|-----------|
| 3 | `src/report_intake/classification/content.py:233` (`_finding`) |
| 3 | `src/report_intake/classification/content.py:256` (`_oversized_leaf`) |
| 3 | `src/report_intake/config.py:34` (`normalize_database_url`) |
| 3 | `src/report_intake/core/body_limit.py:29` (`_declared_length`) |
| 3 | `src/report_intake/core/local_only.py:63` (`_is_loopback_host`) |
| 3 | `src/report_intake/core/local_only.py:82` (`_is_loopback_client`) |
| 3 | `src/report_intake/delivery/dispatch.py:84` (`TicketDispatcher._attempt`) |
| 3 | `src/report_intake/identity/gate.py:65` (`admit`) |
| 3 | `src/report_intake/identity/mesh_identity.py:49` (`peer_in_networks`) |
| 3 | `src/report_intake/identity/mesh_identity.py:78` (`mesh_caller_email`) |
| 3 | `src/report_intake/identity/rate_limit.py:101` (`TokenBucketLimiter.check`) |
| 3 | `src/report_intake/identity/rate_limit.py:154` (`rate_limit_key`) |
| 3 | `src/report_intake/main.py:106` (`_find_forwarded_allow_ips_overlap`) |
| 3 | `src/report_intake/queue_cli.py:181` (`_print_queue`) |
| 3 | `src/report_intake/queue_cli.py:192` (`_print_ticket`) |
| 3 | `src/report_intake/queue_cli.py:217` (`_record_filed`) |
| 3 | `src/report_intake/reports/caps.py:93` (`structural_violation`) |
| 3 | `src/report_intake/reports/caps.py:163` (`_cap_string`) |
| 3 | `src/report_intake/reports/retry.py:224` (`RetryQueue._schedule`) |
| 3 | `src/report_intake/reports/store.py:429` (`ReportStore._record`) |
| 3 | `src/report_intake/reports/store.py:559` (`ReportStore._replay`) |

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

`create_app`: 16 → 18 (`OME-1009`) → 20 (`OME-1010`) → 23 (`OME-1011`) → 24, two under its
threshold and by construction, because every item's wiring lands there as two or three more
lines. The `LinearSink` follow-up added none of it: the composition root still names one sink and
still does not know which adapters exist, so `build_sink(settings)` replaced
`build_sink(settings.ticket_sink)` and nothing else. `_lifespan` moved 14 → 15 for the one line
that closes a sink holding a connection pool, and `delivery/linear_sink.py` itself tops out at
C901 5 / PLR0912 4 / PLR0915 9 — every headline number unmoved for the seventh item running.

The `queue` console follow-up moved none of the four either, and `create_app` is untouched by it —
the drain path is a command, not wiring. Its two new files enter the tables low: `queue_cli.py`
tops out at C901 4 / PLR0911 3 / PLR0915 12, and `cli.py:_parser` is the largest thing this pass
added at PLR0915 16, eight under the threshold. `_parser` is deliberately one flat function: it IS
the entrypoint's argument surface, and splitting a parser across helpers hides which invocation
serves and which drains — the same argument `create_app` wins its own length with. `_record_filed`
sits exactly on `max-returns = 3` because the check for "already filed under a different ticket"
was pushed into `_already_filed`, which is the shape that rule keeps asking for. `OME-1011` kept it to three by putting the whole middleware stack in `_install_middleware`
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
4. PLR0915 `max-statements`: 26 → 24 is what is left, and it now sits EXACTLY on `create_app`
   rather than one above it. The earlier suggestion of 22 is not reachable without splitting the
   composition root, and splitting it is the wrong trade: `create_app` reads top to bottom as
   "what this service is made of", and hiding a third of it behind helpers to satisfy a threshold
   nobody has hit makes the wiring harder to audit, which is the thing the wiring is for. Ratchet
   to 24 only alongside a change that gives the composition root headroom — at the mark, the next
   item's two wiring lines are a red build in an unrelated PR.

**Do not ratchet a threshold below a number this file records without reducing the named
offender in the same PR** — the two move together, or the next contributor discovers the
rule by having their unrelated change rejected.
