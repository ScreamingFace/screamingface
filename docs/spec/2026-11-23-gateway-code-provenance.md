# Gateway code provenance: lift only the codes the Gateway declares

Ledger: `docs/work/2026-11-23-gateway-code-provenance.md`. Plan:
`docs/plan/2026-11-23-gateway-code-provenance.md`. Branch `gateway-code-provenance`, now on
origin/main `d37932d61`. Of its three commits after `a5a7986ec`, two change neither app;
OME-1989 moves Engine lines in `world/connector.py` and `error_text.py`, adds the reserved code
`provider_key_refused`, and changes only logging in the Gateway. Measurements were taken on
`a5a7986ec` and, where that commit could change them, taken again on `d37932d61`. Landings:
`screamingface-engine` (primary) and `aigateway`. The BYOM
routing pilot (`docs/spec/2026-11-04-byom-routing-pilot.md`, section 9; PR #2016) does not merge
before this lands, or before the security owner accepts its risk.

Engine paths are relative to `apps/screamingface-engine/src/screamingface_engine/`, Gateway paths
to `apps/aigateway/src/aigateway/`, unless a path starts at the repo root. Line numbers are those
of `d37932d61`.

## 1. Problem

`world/connector.py::_upstream_code` (`:2040`) lifts the `detail.code` of any non-2xx Gateway
answer unless it names an Engine-reserved code (OME-941). The lifted code then reaches:

- `observation.failed(exc.code)` and the model-call log line `model call failed ... code=`
  (`world/connector.py:310-312`), on every chat, classification and frozen-copy call;
- the public benchmark report: an undeclared code becomes `upstream_error` with its spelling kept
  in `source_code` (`benchmarks/aggregation.py:176-181`). The only screen there is
  `public_identifier` (`error_text.py:138-143`), which keeps any `[A-Za-z0-9_.:-]{1,80}`;
- the run's terminal error and its events.

The HTTP problem body is already closed: `rest/routes.py::_sanitized_error` reports an unvouched
code as `internal_error`.

The connector treats a proxy in front of the Gateway as an assumed threat (`_raise_for_status`).
Such a proxy, or any body that answers in the Gateway's place, can put a key, an origin with a
port, a path or a private model or deployment ID into `detail.code`, and it is lifted. A shape
screen does not help: `byom_secret_deployment_alpha`, `byom-origin.internal.test:8443`,
`hf_<32 chars>`, `ghp_<36 chars>` and `sk_live_abcdef123456` all look like plain identifiers
(review, 2026-11-23).

Today's Gateway does not do this itself. An inventory of its source on `a5a7986ec` found that
every `detail.code` it writes is a fixed literal, picked per site or from a fixed status-to-code
map; no provider's own error code is copied into it. The remote endpoint maps any upstream error
to `provider_error` or `provider_unavailable` (`plugins/remote_endpoint/transport.py:131-140`),
and the OAuth token errors carry literal details (`core/oauth/token_service.py:89-150`). The only
copies are of values the Gateway wrote earlier: the dispatch-failure rewrite
(`core/provider_access/connection_authority.py:176`, `:260`) and the frozen-copy replay of a
captured error (`routes/frozen_copies.py:231-240`). The Gateway's vocabulary is therefore closed
in fact, but nothing declares it and the Engine does not rely on it.

## 2. Decision (owner, 2026-11-23)

A closed, Gateway-owned vocabulary. The Engine lifts a code only when the Gateway declares it;
every other code takes `aigateway_http_<status>`.

What membership proves: the code is a value the Gateway itself defined, so it is safe to log and
publish, and the Engine understands it. What it does not prove: that the Gateway wrote the
response. A proxy can still answer with any declared code, for example a `404`
`unsupported_parameters` that the Engine maps to `logprobs_unsupported` for a call that asked for
log-probabilities. Such a proxy can already forge the answer itself, so a forged declared code
gives it no new reach. Proving the writer needs transport integrity, which is separate work.

Rejected:

- A status-only fallback for every code. It drops what the Engine reads today: the
  `bad_request` relay contract (`tests/unit/test_gateway_error_relay_contract.py`), the
  `logprobs_unsupported` mapping, the frozen-copy outcomes, and the Gateway codes the benchmark
  report declares.
- A shape screen. It keeps every review counterexample.
- An Engine set wider than the Gateway's. A stale, misspelled or speculative Engine-only code
  would stay liftable with no Gateway behind it (review, 2026-11-24).
- A list of pending codes the Gateway does not write yet. No change needs one (section 3.5).

## 3. Contract

### 3.1 The vocabulary

A Gateway-owned fixture, `apps/aigateway/tests/fixtures/gateway_error_codes/codes.json`: a JSON
object with two sorted, disjoint lists.

- `codes`: every code the Gateway source can write as a `code` in a response body, on any route,
  admission answers included. One rule for every Gateway-authored code keeps the check simple,
  and each one is still a Gateway literal.
- `retired`: every code the Gateway wrote on `main` after frozen-copy capture began
  (`f06860621`, 2026-10-12) and no longer writes. A replay reads only a sealed copy and returns a
  captured error's `detail` unchanged (`routes/frozen_copies.py:231-240`). Sealed copies have no
  end date: the sweep (OME-1947, `core/frozen_copy/sweep.py`) deletes the entries of idle open
  copies only, and the planned expiry rule keeps every copy the scoreboard has claimed. So any
  of these codes can reach the Engine again. The first list, from every first-parent snapshot of
  `src/aigateway/` since `f06860621`:
  `credential_write_conflict`, `invalid_profile_defaults`, `profile_auth_conflict`,
  `profile_conflict`, `profile_index_conflict`. All five are kept without proving which of them
  a chat call could reach: each is a Gateway literal, and a wrong exclusion would silently change
  a replay's evidence.

A code never leaves `retired` while a sealed copy can hold it. A change that makes the
Gateway write a new code adds it to `codes`, and to the Engine set, in the same change; a change
that stops writing a code moves it to `retired`.

Only a Gateway built from outside `main` could have stored a code the history does not show. A
read-only query of the hosted store for the distinct `response_json.detail.code` of frozen-copy
entries with a non-200 status can look for one. It is an owner action (section 7), under these
rules:

- The result is sensitive, untrusted evidence. A stored value proves no authorship: it may be a
  key, an origin, a private ID, or a value from a build nobody reviewed. No value outside the two
  lists is copied into this spec, the ledger, a PR, an issue or a log; it is named only by count
  and by the copy and entry that hold it.
- A value joins `retired` only when it is traced to a fixed literal in the source of a Gateway
  build that was deployed to that store.
- A value that is not so traced stays undeclared and takes `aigateway_http_<status>`, which is
  the safe default.

### 3.2 The Gateway check

A Gateway unit test reads `src/aigateway/` with `ast`, `migrations/` excluded (its 15
`RunPython(code=...)` calls name migration functions, not codes). It fails closed: a site that
can put a code into a response and that the check cannot prove literal fails until it is
reviewed.

Code writes. Each must be a string literal in `codes`, or a reviewed site:

- the value of a `"code"` key in a dict literal, which also covers `.update({"code": ...})`;
- the `code=` argument of any call, which also covers `dict(code=...)`;
- a subscript store `x["code"] = ...` and a `.setdefault("code", ...)`;
- the code argument at every call of a reviewed producer (below).

Outbound sinks. The `detail` of each `HTTPException`, the `content` of each `JSONResponse` and the
body of each app-level exception handler must be a string, a dict literal (its code then checked
as above), a module-level constant bound to one of those, or a reviewed site. This is what catches
a detail built elsewhere and forwarded, such as `HTTPException(detail=exc.detail)` or a replayed
`detail`.

Reviewed sites. Each names its file and function, why it is closed, and where its codes come
from: a fixed list, or a producer. A producer is a named callable whose code argument the check
collects at every call site; a non-literal argument there fails. Examples on `a5a7986ec`:
`TavilyDescriptionError`, whose first argument reaches `routes/tavily_retrieval_cache.py:130`;
`ModelAdmission.refused`; the remote endpoint's `_error`. The two copy sites of section 1 are
reviewed as copies of a detail the Gateway wrote. On `a5a7986ec` a prototype of the check counts
28 non-literal code writes, and 35 `HTTPException` and 7 `JSONResponse` sinks whose detail is not
a literal, many of them module constants. The check itself, on `d37932d61`, proves every other
site and leaves 22 it cannot prove: 17 reviewed and 5 not codes (the OAuth authorization code). A
sixth not-code site, the OAuth setting `code="true"`, is a literal, so the tables list 23 sites,
17 reviewed and 6 not codes. It also follows two shapes the prototype missed:
an `HTTPException` subclass with no `__init__` of its own, and a body that wraps a forwarded
`detail` in a dict. The fixture holds 95 codes and the 5 retired ones.

Not codes. A `"code"` key or `code=` argument that is not a response code is listed by site, such
as the OAuth exchange `OAuthCodeExchangeRequest(code=...)` (`routes/auth.py:561`) and the OAuth
setting at `plugins/anthropic_provider/settings.py:69`.

The fixture. A `codes` entry the source no longer writes fails (it moves to `retired`), and so
does a code in both lists. `retired` must equal an audited list in the test, exactly: the Engine
lifts every retired code, so a value that joins the fixture alone fails, and so does an audited
code the fixture drops. A code the Gateway stops writing is added to both in one change.

The test checks itself on synthetic modules. Each of these must fail: a new literal code; a dict
literal with a non-literal code; a subscript store; `dict(code=...)`; `.update({"code": ...})`;
`.setdefault("code", ...)`; `HTTPException(detail=exc.detail)`; a `JSONResponse` that forwards a
stored `detail`; a producer called with a non-literal; a stale `codes` entry; a code in both
lists; a `retired` entry that is not audited, and an audited one the fixture drops.

The check is static: it fails closed on every shape it does not know, but it cannot prove a
reviewed site's reason. One Gateway constructor for every error detail would shrink it; that is
a possible later change, not part of this unit.

### 3.3 The Engine rule

`GATEWAY_CODES`, a frozenset in a new Engine module `world/gateway_codes.py` (`connector.py`
already has 2132 lines). `_upstream_code` returns the detail's `code` only when it is a string in
`GATEWAY_CODES`; otherwise it returns `aigateway_http_<status>`. `GATEWAY_CODES` never meets
`ENGINE_RESERVED_CODES` (section 3.4), so the OME-941 rule holds by construction; the reserved
check stays in `_upstream_code` as a guard. Permanence (`False` only for `429` and `5xx`), the
message, the plain `detail` text and the translated refusal (`intent_error_for`) are unchanged.

The refused-key watch (OME-1989, `world/refused_key_stop.py`) reads the lifted code. Its two key
codes, `auth_required` and `insufficient_credits`, are declared, so they still reach it. A `403`
counts toward one model's streak while the code stays the same; two undeclared `403` codes are
now both `aigateway_http_403`, so they extend one streak instead of starting a new one. A code
the Gateway writes is unchanged.

### 3.4 Parity

An Engine unit test reads the fixture and fails unless both hold:

- `GATEWAY_CODES == (codes | retired) - ENGINE_RESERVED_CODES`. Exact, so the Engine lifts no
  code the Gateway does not declare, and a declared code it misses fails too.
- `(codes | retired) & ENGINE_RESERVED_CODES == {"frozen_copy_miss", "frozen_copy_unavailable",
  "result_too_large"}` (`error_text.py:77-86`). The Gateway writes these three and the Engine
  keeps them as its own: the two replay refusals are read before `_raise_for_status`
  (`world/connector.py::_replay_refusal`), and `result_too_large` is the Engine's own delivery
  failure. Pinning the overlap makes a new collision fail until it is reviewed.

The Gateway's `410` `frozen_copy_expired` is also read by `_replay_refusal` first, and leaves the
Engine as `frozen_copy_unavailable` (OME-1947). It is not reserved, so it is in `GATEWAY_CODES`
like any declared code; outside a replay it is lifted as itself.

The Engine workflow (`.github/workflows/screamingface-engine-tests.yml`) adds the fixture
directory to its push and pull-request path filters, as it does for the other Gateway-owned
fixtures, so a Gateway change to the vocabulary runs the Engine suite in the same PR.

### 3.5 Rollout

The Gateway and the Engine are built and released by separate workflows
(`release-aigateway.yml`, `release-screamingface-engine.yml`), so one PR does not order their
deployment.

- This unit changes no Gateway runtime code: its Gateway landing is a fixture and a test. Only
  the Engine artifact changes behavior, so nothing needs ordering.
- A later change that adds a code puts it in the fixture and in `GATEWAY_CODES` in one PR. If the
  Gateway is deployed first, the Engine reports that code as `aigateway_http_<status>` until its
  own deployment: less specific, never a leak. A change whose Engine behavior, not only its
  report, depends on the new code says in its PR that the Engine deploys first.
- A code the Gateway stops writing moves to `retired` and stays there (section 3.1).

### 3.6 Unchanged, and out of scope

Unchanged: the HTTP problem body policy; `/route-answer` and its relay rule (pilot spec 6.1, C9);
`DECLARED_FAILURE_CODES`; message relay and its parity (OME-1136); the exact-string match of
`unknown provider: <provider>` (`world/connector.py:2037`).

Out of scope, of the same kind: the Engine's model-parameter proxy keeps the Gateway's answer
verbatim on its public routes (`catalog/executable.py:268`) and relays an admission refusal's
`code` and `message` (`catalog/aigateway.py:217`, `catalog/executable.py:383`). Neither passes
through `_upstream_code`. Because admission codes are in the vocabulary (section 3.1), a later
unit can close that relay against the same set.

## 4. Blast radius

Measured, not searched for: the Engine unit suite was run on `a5a7986ec` under the current rule
(10302 passed) and under the closed rule with a candidate vocabulary built from the inventory
(10294 passed). Exactly six prior test functions (eight cases) turn red, the same six as on
`de16e8e94`, and each asserts that a code the Gateway never writes passes through:

- `tests/unit/test_aigateway_connector.py:396-420`: `invalid_credential` (`401`),
  `quota_exceeded` (`402`), `upstream_unavailable` (`503`);
- `tests/unit/test_candidate_call_retry.py:84-95`: `bad_gateway` (`502`);
- `tests/unit/test_frozen_copy_replay_failures.py:98-115` and
  `tests/unit/test_frozen_copy_replay_unserved.py:100-108`: a replayed `500` `boom`;
- `tests/unit/test_unsupported_content_part_refusal.py:66-81` and
  `tests/unit/test_mount_routes.py:561-575`: `provider_refused` (`422`).

Changing any of them is a change to a prior test and needs the owner's approval of its exact
blobs at implementation. The proposed changes:

- The two replay tests keep `boom` and expect `aigateway_http_500`. Their claim is that a replayed
  error is handled as a live one, and a live undeclared code now takes the fallback. Swapping
  `boom` for a current code would stop testing an undeclared code at all. A new test replays a
  retired code unchanged (section 5).
- The others take a declared code with the same status and permanence.

`tests/unit/test_gateway_error_relay_contract.py` stays green: `bad_request` is declared. Every
model call's lifted code becomes closed, so the pilot's merge gate is released.

## 5. Tests

Engine:

- every review counterexample and every path, origin, key and private-ID shape takes
  `aigateway_http_<status>` at `400`, `429` and `502`, with permanence kept;
- every code in `GATEWAY_CODES` is lifted unchanged; the three codes of the pinned overlap and
  every other `ENGINE_RESERVED_CODES` code are not;
- an undeclared plain identifier takes `aigateway_http_<status>`;
- a replayed captured error with a retired code (`profile_index_conflict`) keeps that code, and a
  replayed undeclared code takes the fallback;
- the model-call log line and the observation never carry an undeclared code;
- the benchmark report, exactly: an undeclared code at `502` gives `code ==
  "aigateway_http_502"`, `source_code is None` and `retryable is True`, and at `400` gives
  `aigateway_http_400` and `retryable is False`, because `aigateway_http_<status>` is itself
  declared (`benchmarks/contract.py:187-189`); the undeclared spelling appears nowhere in the
  report; a declared Gateway code outside `DECLARED_FAILURE_CODES` still gives `upstream_error`
  with that code as `source_code`;
- `logprobs_unsupported` still maps from a 404 `unsupported_parameters`;
- parity, as in section 3.4.

Gateway: the check of section 3.2, with its synthetic self-test.

## 6. Landings, tickets and ownership

Two landings in one PR, so two leaves under one epic, `OME-1306`, whose pilot this unit
unblocks:

- the Engine leaf, OME-2010, is primary: the branch `OME-2010-gateway-code-provenance` takes its
  number, the shared ledger's `ticket:` names it with the Gateway leaf beside it (as the pilot
  ledger does), and the approval manifest of the Engine prior tests is filed under it;
- the Gateway leaf, OME-2011, is its sibling: the fixture and the Gateway check.

Each leaf has its own `docs/tasks/` mirror; the PR body has `Refs:` for both. The mirror check
reads one ledger per ticket and reports, but never fails, a mirror with no ledger
(`.claude/scripts/check_mirror_status.py`). The leaves are filed when the PR opens, after the
user confirms them.

## 7. Owner decisions

- Q1 (answered 2026-11-24): the Gateway fixture with a Gateway-side check.
- Q2 (answered 2026-11-24): the strategy of section 4 is approved, and after the full Engine run
  the owner approved the six prior-test changes at their exact blobs (ledger, Planned changes).
  Any other change to them needs a new approval. The approval manifest pins the blobs under the
  Engine leaf and the renamed branch when the PR opens.
- Q3 (answered 2026-11-24): epic `OME-1306`, two leaves, the Engine leaf primary.
- Q4 (answered 2026-11-24): Q4 not run. Residual compatibility risk: a frozen copy produced by an
  unknown non-main Gateway build may replay as aigateway_http_<status> rather than preserving its
  original code. Confidentiality remains closed because no observed production value becomes
  trusted vocabulary without source provenance. It blocks neither implementation nor merge.
