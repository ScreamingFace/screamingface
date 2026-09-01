---
ticket: OME-967
stack: screamingface
status: in_progress
started: 2026-09-01
finished:
---

# OME-967 — Originate the traceparent in the client and surface `trace_id`

## Intent

The keystone of the correlation roadmap (epic `OME-935`). Today the trace id is minted
*inside the Runner Job* (`url4/streaming/lifecycle.py:199-204`) and never returned, and the
client sends no trace context at all — the audit captured request header keys
`['accept','accept-encoding','connection','content-length','host','user-agent']`,
`traceparent present? False` on both the HTTP start and the WS upgrade.

Two consequences, and the first is the one that matters:

1. **Every failure before the first frame has no id at all** — capability mint, run start,
   WS handshake. Permanently unjoinable, and a large share of what users actually hit.
2. Even for runs that start, the user cannot quote an id: `traceparent` reaches
   `sf.Event.traceparent` but has **zero read sites**, and `ExecutionError` exposes only
   `code/details/hint/message/permanent/status`.

The Engine already adopts an inbound traceparent (`rest/routes.py:448-451`, `:479`) and
fails soft to server minting, so **no server change is required**.

## Design decisions

**D1 — mint locally; do not depend on `url4`.** `packages/screamingface`'s dependencies are
`httpx`, `pynacl`, `pyyaml`, `websockets` — `url4` is not among them, and adding a
distribution dependency to the client to obtain 4 lines of string formatting would be the
wrong trade. A small private module mints and formats the W3C value with `secrets`. The
ticket's "do not add an OTel SDK" constraint is honoured, and `url4/streaming/trace.py` is
untouched (it is pinned by url4's own tests).

**D2 — the id goes on `ScreamingFaceError`, not only on `ExecutionError`.** This is a
deliberate widening of the ticket's wording, because the ticket's own consequence #1 is
about failures *before the first frame* — and those raise `EngineUnavailableError` and
`AuthenticationError`, never `ExecutionError`. Putting the field only on `ExecutionError`
would leave the exact class this ticket exists to fix without an id. The base class is the
one place that covers all of them.

**D3 — mint before the capability call, not before the run start.** Same reason: a
capability-mint failure is one of the three unjoinable classes. The trace has to exist
before the first outbound request of the run, not before the second.

**D4 — the client mints `-01` (sampled), matching url4's `format_traceparent`.** The audit
noted that an inbound `-00` is re-stamped `-01` because `_SAMPLED` is hardcoded, which is a
real W3C deviation. It is **out of scope here**: it lives in `packages/url4`, a separate
distribution with its own gate, and changing it is a url4 behaviour change pinned by url4
tests. Filed as a follow-up rather than smuggled into a client ticket. The client emitting
`-01` is consistent with what the engine would produce anyway, so this unit introduces no
new inconsistency.

**D5 — inbound span ids being discarded is likewise out of scope.** The engine adopts the
trace id but mints a fresh root span. That is engine-side, it does not affect whether the
client's id joins (the *trace* id is the join key), and the ticket lists it as "to be
decided", not "to be fixed".

## Planned changes

- `src/screamingface/_engine/trace.py` *(new)* — mint a W3C trace id + span id, format a
  `traceparent`. Private module, no new dependency.
- `src/screamingface/errors.py` — `trace_id` on `ScreamingFaceError` (D2), surfaced in
  `_render_traceback_` so a failed run prints the id the user can quote.
- `src/screamingface/_core/ports.py` — `trace_id` on `_RunOutcome`.
- `src/screamingface/_engine/transport.py` — thread the minted traceparent through
  `_mint_sync`/`_mint_async` (D3), `_start_sync`/`_start_async`, and the WS upgrade
  (`_websocket_url` / connect headers); attach the id to the errors raised on those paths.
- `src/screamingface/_engine/contract.py` — carry the id onto `_RunOutcome`.
- `tests/public_surface_snapshot.json` — regenerated; `trace_id` is a public surface
  addition on the error hierarchy.

**Deferred, with reasons stated above:** the url4 `-00`→`-01` re-stamp (D4), engine span-id
adoption (D5), and `runtime.log` line prefixes — the ticket names the last in "The work" but
not in "Verify", and it is server-side runtime logging rather than client origination.

## Test plan

RED first, behaviour-named, in the house style:

- The client sends a well-formed `traceparent` on the run-start request.
- The client sends one on the capability mint too — the first outbound call of the run.
- The WS upgrade carries the same trace id as the HTTP start (one id per run, not two).
- A run-start failure (`EngineUnavailableError`) carries the trace id — the pre-first-frame
  class from consequence #1.
- A failed run surfaces the id on `ExecutionError`, and it is rendered to the user.
- The id the client holds equals the id on the frames it receives (the ticket's second
  Verify item; asserted against the harness's event stream).
- Boundary: the minted value matches the W3C shape url4's `_TRACEPARENT_RE` accepts, and its
  trace id is neither all-zero nor uppercase.

## Acceptance

- `traceparent` present and well-formed on capability mint, run start, and WS upgrade.
- One trace id per run across all three.
- Every error raised on those paths carries `trace_id`; a failed run shows it to the caller.
- No prior test modified; `run_gates.py screamingface` green (incl. `--cov-fail-under=95`).

## Confidence-Gate decision — the shared protocol fixture was edited (owner, 2026-09-01)

`run_gates.py`'s append-only check failed on `tests/protocol_server.py`, reporting new
content inserted after old lines `[118, 211, 303]` — inside existing handler methods. SDLC
rule 5 makes that the owner's call, so it was put to them with the diff and **approved**;
the gate was then re-run with the documented `--skip-append-only`.

**Nothing was weakened.** The change is **17 insertions, 0 deletions, 0 assertions removed
or changed** — verified, not asserted. It adds to `ProtocolState`:

- a `traceparents: list[tuple[str, str | None]]` field,
- `record_traceparent()` and `trace_ids()`,
- three one-line capture calls in `do_POST`, `_start` and `_accept_websocket`.

That is the same shape as the fixture's existing `http_auth_schemes` and `artifact_requests`
captures: pure observation, appended under the lock the fixture already holds. No existing
test's behaviour changes; the server simply records one more inbound header.

Two alternatives were considered and rejected. **httpx event hooks** would assert on the
client's own object rather than on what reached the wire, and cannot see the WebSocket
upgrade at all (that goes through `websockets`), losing the third leg — the one the ticket
calls out by name. **A second protocol server** would duplicate ~600 lines of protocol
handling and drift from the original, which is precisely what one shared fixture prevents.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_engine/trace.py` (new), `errors.py`, `_core/ports.py`,
  `_engine/transport.py`, `tests/test_client_protocol.py`, `tests/protocol_server.py`
  (fixture capture, approved above), `tests/public_surface_snapshot.json` (regenerated).
  **`_engine/contract.py` was NOT touched** — see Deviations.
- **Commits:** `feat(screamingface): originate the traceparent in the client` (sha assigned
  at squash-merge).
- **Gates:** `run_gates.py screamingface --skip-append-only` — **ALL GATES GREEN**: ruff ·
  ruff format · pyright · `pytest --cov=screamingface --cov-fail-under=95` (**1295 passed,
  17 skipped**, coverage 95.06%) · check_notebooks · uv build · check_distribution. RED was
  confirmed first: all six new tests failed, the last on
  `TypeError: ScreamingFaceError.__init__() got an unexpected keyword argument 'trace_id'`.
- **Deviations:**
  - **`_RunOutcome.trace_id` is stamped in `transport.py`, not `contract.py` as planned.**
    The contract layer decodes what the *Engine* sent; this id is what the *client* minted.
    Only the transport holds it, so stamping it there via `_dataclass_replace` keeps the
    decoder honest about its own inputs.
  - **The id had to reach `_raise_response`, which the plan did not anticipate.** The
    pre-first-frame test failed even after the transport-error branches carried the id,
    because a rejected start returns an Engine `problem+json` and raises through
    `_raise_response` — the far more common shape of that failure. Threading it there covers
    mint, start, stop and artifact from one place.
  - **Two re-mint paths needed the trace threaded through their methods.** Ruff caught
    `undefined-name: trace` in `_remint_after_challenge` and the async
    `_on_handshake_rejection`: an Access challenge mid-run mints a fresh capability, and
    those methods did not have the run's trace in scope. They now take it, so a reconnect
    stays on one trace id rather than starting an unlabelled leg.
  - **`ProviderConnectionError` and `LeaderboardError` do not take `trace_id`.** They are
    raised on provider and scoreboard paths that originate no client trace today; adding an
    untested parameter would be production code no test demanded (rule 4).
  - **`runtime.log` line prefixes remain unimplemented**, as flagged in Planned changes —
    the ticket names it under "The work" but not under "Verify", and it is server-side
    runtime logging rather than client origination.
  - **Public surface changed deliberately.** `trace_id` is now a keyword-with-default on
    five `__init__` signatures; the snapshot was regenerated through the documented
    `UPDATE_SURFACE_SNAPSHOT=1` path. Additive only — no signature lost a parameter, so no
    caller breaks. The changelog entry comes from the conventional commit via release-please
    rather than a hand edit.
