---
ticket: OME-1134
stack: screamingface-engine
status: done
started: 2026-10-01
finished: 2026-10-01
---

# catalog-traceparent-uncoalesced — forward the caller's traceparent on the two uncoalesced catalog calls

## Intent

`OME-1119` left the whole catalog path untraced because `CachedCatalog` coalesces concurrent
`fetch` misses. That argument holds only for `fetch`. `fetch_model_parameters` (REST
`GET /v1/model-parameters`) and `admit_model` (reached from `catalog/executable.py`) each make
one upstream call per inbound request, so they should carry that request's `traceparent` to
aigateway. The value is threaded explicitly from the REST edge. It is NOT put on `Credential`:
that type derives the catalog cache key, so a per-request field would give every request its own
cache entry.

## Planned changes

- `catalog/port.py`: `ModelParameterSource.fetch_model_parameters` gains keyword-only
  `traceparent: str | None = None`.
- `catalog/admission.py`: `ModelAdmissionSource.admit_model` gains the same keyword.
- `catalog/aigateway.py`: `_headers(credential, traceparent=None)`; `fetch` passes none
  (explicitly); `fetch_model_parameters`/`admit_model` pass theirs; `_request` forwards it.
- `catalog/executable.py`: `ExecutableModelParameterSource` threads it to every inner fetch and
  to `admit_model`.
- `rest/catalog.py`: the model-parameters route reads `traceparent`, screens it with
  `valid_traceparent` (malformed → absent, as `rest/connections.py` does), passes it on.
- Owner-approved (option A, 2026-10-01): signature-only keyword on 9 prior test fakes, recorded
  in `.claude/test-change-approvals/OME-1134.json`.

## Test plan

New file `tests/unit/test_catalog_traceparent.py`:
- adapter: `fetch_model_parameters` and `admit_model` send the given traceparent; `fetch` sends
  no `traceparent` header (explicit assertion); default (none given) sends none.
- executable: the traceparent reaches the inner source on the declared, overlay and
  admission paths, and reaches `admit_model`.
- REST: a valid inbound traceparent reaches the source; malformed/absent → `None`.
- cache invariant: two `GET /v1/models` requests differing only in `traceparent` hit one cache
  entry (one upstream fetch, `entry_count == 1`), and that upstream fetch carries no traceparent.

## Acceptance

- The four Verify bullets of `OME-1134` hold, each pinned by a test.
- `run_gates.py screamingface-engine` green (incl. `check_layering.py`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (`catalog/{port,admission,aigateway,executable}.py`,
  `rest/catalog.py`, new `tests/unit/test_catalog_traceparent.py` with 15 tests), plus the
  approval manifest `.claude/test-change-approvals/OME-1134.json` and the mirror
  `docs/tasks/2026-09-07-OME-1134-catalog-traceparent-uncoalesced.md` (`in_review`).
- **Commits:** `feat(engine): forward the caller's traceparent on the uncoalesced catalog calls`
  (sha in the PR).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` gave ALL GATES GREEN: ruff
  check, ruff format, pyright 0 errors, `check_layering.py`, pytest 4388 passed / 67 skipped,
  coverage 93.90% (floor 80). The append-only check, run separately, flagged exactly the 4
  owner-approved files and nothing else.
- **Deviations:**
  - Prior tests changed under owner approval (option A, Sergey, 2026-10-01). The edit is
    signature-only: 8 fake methods in 4 files, not the 9-in-5 first estimated, because
    `test_selector_refusal.py` reuses the proxy file's fake. The Python append-only checker has
    no approval path (`approved_test_changes.py` covers TS/TSX only), so the gates ran with
    `--skip-append-only` after that separate check.
  - Ticket references that moved: the `rest/catalog.py` call is now at line 208 (ticket says
    190). `adapters/k8s.py` no longer exists; the "malformed degrades to absent" precedent is
    `rest/connections.py::_caller` (`valid_traceparent`).
  - The trace is forwarded verbatim once validated (flags preserved), matching
    `rest/connections.py`. It is not re-rendered the way `request_scope.trace_from_headers`
    does.
  - The ledger was renamed to include the ticket id, and the mirror was created at PR-open
    (it did not exist).
