# OME-1183 — config carriers, request-time enforcement, and the catalog gate

**Status:** implemented on `OME-1183-url4-discovery-implementation`; not merged.
**Parent spec:** `docs/spec/2026-09-11-OME-1183-config-schema-scopes.md` (branch
`OME-1183-config-schema-scopes`) — the physical model, scope ladder and `.well-known`
layout are locked there and are NOT restated here.

This document records what that spec left open or did not reach: **D1** (now decided),
**D2** (applied), the shape of request-time enforcement, and the contract of the catalog
linter. It is written after the fact because the decisions were taken during
implementation, with the code as the evidence.

---

## 1. D1 — where user-scope values travel — DECIDED

**Both carriers are valid. Neither is preferred.**

| carrier | shape |
|---|---|
| WebSocket | a `config` member on the attach frame — JSON, native types |
| plain HTTP | one `URL4-Config-<dotted.item.path>` header per item |

### 1.1 One payload, two envelopes

Both parse into the same flat map of dotted item path to value, and **one** enforcement
pass runs over it. This is the load-bearing property, not a convenience: the transports
cannot disagree about what was sent, and there is one error vocabulary for both.

`tests/unit/test_config_carriers.py::test_both_carriers_produce_the_same_payload` pins it.

### 1.2 The header name carries the dotted path verbatim

An earlier reading of this problem assumed the path had to be flattened into a header
name, and that `parameters.top_p` would therefore collide with a hypothetical
`parameters.top.p`. **That is wrong.** `.` and `_` are both legal in an HTTP field name —
RFC 9110 `token` admits `!#$%&'*+-.^_`|~` alongside alphanumerics — so the path survives
unchanged and no encoding is needed.

Removing that objection is why "both valid" is a clean design rather than a compromise.

### 1.3 The cost, and how it is paid

A header value is always a string. `carrier.coerce()` types it **using the schema the
caller was already served**, so `"0.7"` becomes `0.7` because the item declares `number`.

A value that does not parse is deliberately left as the string, so `scope.enforce` reports
a type mismatch naming the DECLARED type. Same error either way.

Booleans accept only `true`/`false`. Accepting `yes`/`1` would make the header carrier
lenient where the attach frame is strict, and the two must agree.

### 1.4 Deployment hazard — nginx and underscores

**nginx silently DROPS headers whose names contain an underscore** unless
`underscores_in_headers on`. So `URL4-Config-parameters.top_p` vanishes, and the request
runs on the default with no error.

Nothing can distinguish "dropped" from "not sent" — the header is simply gone. So
`carrier.missing_underscored()` exists as an OPERATOR HINT, not a check: it lists the
user-scope item paths containing `_` that a given request did not carry. A node deployed
behind nginx must set that directive.

---

## 2. D2 — suffix name — APPLIED

`url4-` everywhere, in paths AND in field names. `abc_version` → `url4_version`,
`abc_delegate` → `url4_delegate`. Part G's `abc-` spelling is dropped; neither was
IANA-registered.

---

## 3. Request-time enforcement

### 3.1 The rule

> **Never answer `200` to a request carrying config the node did not apply.**

A `200` means "I did what you asked". A node that serves a permission model and then
silently ignores values sent against it has told the caller their values were honoured.
Their eval run is then wrong and nothing said so — which is strictly worse than an error,
because an error gets fixed in a minute.

### 3.2 Which schema judges the values

Config is per-ENDPOINT, so the node reads the routes the expression addresses and matches
them against the mount table. **Two AST shapes reach a route and both count:**

* `RelExpr.path` — `/claude-fast(ctx)!'intent'`, an endpoint CALL
* `RelUrl.value` — `(/claude-fast)!'intent'`, the same route read as a SOURCE

Collecting only the call form would let a caller address a mount the other way and have
their config silently dropped — the same bug in a new costume.

### 3.3 Three cases are refused rather than guessed

| situation | refusal |
|---|---|
| no mounted endpoint addressed | no schema exists to judge against |
| several mounts addressed | config is per-endpoint; which one is ambiguous |
| the mount is `unavailable` | the node holds no schema for it |

Applying one endpoint's config to another is a silent wrong answer, which is the failure
this whole layer exists to prevent. Declining is strictly better.

### 3.4 Valid config returns `501`, not `200` — DELIBERATE

When values ARE the caller's to set and pass every check, the node still refuses, with
`501` and a problem saying why: **forwarding config to a mounted endpoint does not
exist.** Mounts are discovery-only today — `build_node` never routes to them, and the
composer that would (OME-1187) is unwritten.

`200` here would be the identical lie, merely harder to spot because the values were
correct. When mount forwarding lands, this branch becomes the forward and the `501` goes
away. Confirmed with the owner 2026-09-16.

### 3.5 Problem shape

RFC 9457, `type: https://url4.ai/problems/config-rejected`, `status: 400`, with a
`violations` extension member listing EVERY violation — a caller who sent four bad values
should need one round trip, not four. Codes: `config-scope-violation`,
`config-not-settable`, `config-out-of-enum`, `config-type-mismatch`,
`config-unknown-item`. They are wire-visible, so renaming one is a breaking change.

A `writeOnly` item is refused as a SECRET (`config-not-settable`), not as a scope error:
someone sending `credentials.api_key` is injecting a credential, not misreading the
ladder, and the message should say so.

---

## 4. The catalog linter

### 4.1 Why it must exist

`x-scope` is not a JSON Schema keyword, and 2020-12 §6.5 **requires** a validator to
ignore keywords it does not recognise. Every validator on earth therefore calls a catalog
with a scopeless leaf valid. Only a parallel walk says otherwise.

A catalog with a missing `x-scope` is not a strict catalog — it is one with a HOLE:
`resolve_item` does not find the leaf, and `enforce` reports a legitimate value as an
unknown item.

### 4.2 Rules

* every leaf declares `x-scope` (in the ladder), `type` and a non-empty `description`
* every group is closed with `additionalProperties: false` — an open group accepts a
  typo'd item name, and an accepted typo is a setting that silently never takes effect
* a `writeOnly` item carries no `default` — the catalog is SERVED, so that default is a
  published credential
* a `system` item is `readOnly` or defaulted, else nothing can ever give it a value
* a `default` satisfies its own `type` and `enum`
* `$ref`, `$defs`, `oneOf`, `anyOf`, `allOf`, `not`, `if`/`then`/`else`, `$anchor`,
  `dependentSchemas` are rejected — a catalog is INLINED into the node's bundle, where a
  local `$defs` collides and a `$ref` resolves against the wrong base; and an applicator
  would make an item's scope depend on the instance, which discovery must answer without

### 4.3 The group/leaf discriminator is `x-scope`, not `properties`

**An object carrying `x-scope` is a LEAF** whose value happens to be an object —
`parameters.response_format` is one setting, not a namespace of sub-items. Keying this on
`properties` turns that item into a group and makes its scope unenforceable. There is
exactly one instance in the real corpus, so a fixture that omits it passes a broken
implementation; `test_catalog_lint.py` carries one deliberately.

### 4.4 The gate, and the vacuous-green trap

`.github/workflows/catalogs.yml` runs `.github/scripts/lint_catalogs.py` over the repo,
path-filtered on `**/*.schema.json`. Its own workflow rather than a job in the url4 lane
because `paths:` is workflow-level: a job inside that lane would run url4's whole matrix
on every schema edit AND would not fire for a catalog committed elsewhere. Same reasoning
`charts.yml` already uses.

**No catalog is committed yet**, so a naive gate would find zero files and exit `0` —
indistinguishable from one that works. The gate therefore **proves itself first**: it
lints a known-bad fixture and fails if the defect is not caught. Exit codes are `0` clean,
`1` defects found, `2` **the gate itself is broken**.

Catalogs are discovered by CONTENT (`$id == "url4-config"`), not by filename — keying on a
naming convention would silently skip one that did not follow it.

`--require-at-least 0` is correct while none are committed; the run prints the count so a
drop from N to 0 is visible. **Raise it in the commit that lands the catalogs.**

---

## 5. What this does NOT deliver

* **Mount forwarding.** Mounts are discovery-only. §3.4 is the consequence.
* **The catalogs themselves.** The parent spec puts them in
  `docs/spec/2026-09-11-OME-1183-config-schemas/`. They exist, untracked, and are used as
  the corpus the implementation was built against — deliberately not committed yet.
* **`/v1/models` retirement.** Needs the client repo.

## 6. Traceability

| decision | code | tests |
|---|---|---|
| D1 both carriers | `url4/discovery/carrier.py` | `test_config_carriers.py` (41) |
| scope ladder, at rest and in flight | `url4/discovery/scope.py` | `test_config_walk.py` (21) |
| request-time enforcement | `url4/discovery/request.py` | `test_request_enforcement.py` (18) |
| the three documents | `wellknown.py`, `compose.py`, `resolver.py` | `test_discovery_mounts.py` (32) |
| catalog linter | `url4/discovery/catalog.py` | `test_catalog_lint.py` (40) |
| the gate | `.github/scripts/lint_catalogs.py` | `test_lint_catalogs.py` (11) |
