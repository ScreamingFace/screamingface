# Unit 2 — Real config sections and the mount collision guard (F3 + F4)

**Depends on:** unit 1.
**Behaviour change:** new mount kinds become registrable. No new HTTP surface.
**Reviewable as:** a config-surface addition plus a startup invariant.

## 1. User story

> As an operator, I want to declare data, holdings and identity routes in
> `url4.toml` and have the engine register them on the same node that serves model
> routes, so that the engine's addressable surface is the one url4 documents rather
> than a subset the engine invented.

And, as the engineer who has to keep D3 safe:

> As an engine maintainer, I want a startup check that fails when a mount path is
> shadowed by an engine route, so that route precedence is an enforced invariant
> instead of an accident.

## 2. What changes

### F3 — `[data]`, `[holdings]`, `[identities]`

`world_config.py:252-259` currently raises `WorldConfigError` for all four reserved
sections. Three of them become real, delegated to url4's own resolvers
(`cli/_config.py:189-212`) and registered with `node.data()`, `node.holdings()` and
`node.identity()`.

Restrictions, from `ans:Q2`:

| Section | v1 |
|---|---|
| `[data]` | `value` and `file` providers only. `command` providers **rejected**. |
| `[holdings]` | Allowed. Global to all callers (D8). |
| `[identities]` | Allowed. Global to all callers (D8). |
| `[commands]` | **Rejected entirely.** Still raises `WorldConfigError`. |

`[commands]` registers argv templates as exec mounts. On a shared, network-reachable
tier with no per-request memory ceiling, that is a remote-code-execution surface with
no sandbox. The worker path's `RLIMIT_AS` isolation does not exist on the node tier.
Deferred deliberately. [`ans:Q2`]

### F4 — the collision guard

Under D3 the node keeps `eval_path="/v1"` and collisions are resolved by FastAPI
route precedence. Precedence is a silent mechanism: a literal route added later
shadows a mount, and the only symptom is a mount that stops answering.

The guard makes it loud. At startup, in **both** shapes:

1. Collect the node's registered mount paths and its `eval_path`.
2. Collect the engine's literal route paths.
3. Fail if any mount path is equal to, or shadowed by, an engine literal route.
4. Fail if any engine literal route would shadow the eval path's prefix in a way
   that removes it entirely.

url4's own `_check_routable` (`peer/server.py:207-213`) already rejects duplicates
*within* the node. F4 covers the engine-versus-node case that url4 cannot see.

## 3. Acceptance criteria

### AC1 — declared data routes resolve (happy path)
> **Given** a `url4.toml` declaring `[data]` entries with `value` and `file` providers
> **When** the world is built
> **Then** each declared path is a registered mount
> **And** reading it returns the provider's content with its declared media type.

### AC2 — holdings and identities resolve (happy path)
> **Given** `[holdings]` and `[identities]` declarations
> **When** the world is built
> **Then** the default shelf and each named identity shelf are registered
> **And** an unknown identity resolves to url4's `unknown_identity` error.

### AC3 — command-backed data is rejected (failure path)
> **Given** a `[data]` entry whose provider is `command`
> **When** config is loaded
> **Then** loading fails with a named error identifying the path and the provider kind
> **And** the process does not start.

Rejecting at load rather than skipping is deliberate. A silently omitted mount is a
mount that 404s in production with no explanation. [proposed]

### AC4 — `[commands]` is still rejected (failure path)
> **Given** a `url4.toml` containing a `[commands]` section
> **When** config is loaded
> **Then** it fails with an error stating the section is not supported
> **And** the message explains that exec mounts are deferred, not forgotten.

### AC5 — a shadowed mount fails startup (failure path)
> **Given** a world whose mount set contains a path equal to an engine literal route
> **When** the process starts
> **Then** startup fails, naming both the mount and the shadowing route
> **And** no request is ever served by the half-built process.

### AC6 — the eval path survives precedence (edge)
> **Given** the node's `eval_path="/v1"` and the engine's `/v1/models`,
>   `/v1/benchmarks`, `/v1/connections`
> **When** the collision check runs
> **Then** it passes, because those are strictly longer literal paths
> **And** a hypothetical engine route at exactly `/v1` fails the check.

This is the case D3 depends on. It must be pinned by a test, because it is the
difference between "precedence works" and "precedence silently ate the eval path".

### AC7 — declared shelves are logged at startup (edge)
> **Given** any `[holdings]` or `[identities]` declaration
> **When** the process starts
> **Then** it logs, at INFO, each declared shelf and a statement that shelves are
>   readable by every caller of the sync surface.

Under D8 the sharing is intentional. Making it visible at boot is what keeps it from
becoming an accident. [`ans:Q9`]

### AC8 — encoded route ids remain addressable (edge)
> **Given** a model id containing a colon, encoded by `encode_route_id` to a tilde
> **When** the mount set is built
> **Then** the mount path uses the encoded form
> **And** the collision check compares encoded forms, not raw ids.

## 4. Out of scope

- `[commands]` and exec mounts of any kind.
- Per-caller scoping of holdings or identities (D8).
- Serving `.well-known/url4-*` documents or a mount table. That is OME-1187.
- Any HTTP exposure of the new mounts. They become registrable here and reachable in
  unit 3.

## 5. TDD plan

Risk order: a wrongly-permitted exec surface is worse than a wrongly-rejected
config, and a silently shadowed mount is worse than a noisy failure.

### T1 — command-backed data provider is rejected (AC3)
**RED** — Load a config with a `command` provider under `[data]`; expect a named
error. Fails while the section is rejected wholesale for the wrong reason, and
fails again once the section is accepted without the restriction.
**GREEN** — Parse `[data]`, then reject non-`value`/`file` providers explicitly.
**Refactor** — Share the provider-kind vocabulary with the error message so they
cannot drift.

### T2 — `[commands]` stays rejected (AC4)
**RED** — Load a config with `[commands]`; expect the unsupported-section error with
the deferral wording.
**GREEN** — Keep the existing rejection; update the message.
**Refactor** — none.

### T3 — a shadowed mount fails startup (AC5)
**RED** — Build a world whose mount set includes a path colliding with an engine
literal route; assert startup raises and names both. Fails before the guard exists.
**GREEN** — Implement the guard in the shared composition helper used by both shapes.
**Refactor** — Run it from one place so the two shapes cannot diverge.

### T4 — `/v1` precedence is exactly as assumed (AC6)
**RED** — Assert the real engine route set plus `eval_path="/v1"` passes, and that
adding a literal `/v1` route fails. Fails before the guard exists.
**GREEN** — Comparison logic that understands longer-literal-wins.
**Refactor** — Document the rule next to the check, citing D3.

### T5 — data, holdings and identities resolve (AC1, AC2)
**RED** — Declare one of each; assert each is registered and returns its content.
Fails while the sections raise.
**GREEN** — Delegate to url4's resolvers and register.
**Refactor** — Keep the engine's config dataclasses thin wrappers over url4's, so
url4 remains the single source of provider semantics.

### T6 — encoded ids are compared consistently (AC8)
**RED** — Include a colon-bearing model id; assert the mount path is the encoded
form and the guard compares encoded forms.
**GREEN** — Encode before comparison.
**Refactor** — none.

### T7 — shelves are logged (AC7)
**RED** — Assert the startup log contains each declared shelf and the visibility
statement.
**GREEN** — Emit at INFO during registration.
**Refactor** — none.

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| An operator puts secrets in `[holdings]`, assuming per-caller scoping | **High** | **High** | AC7 startup log; explicit wording in `url4.toml` comments and the engine README |
| A `file` provider reads a path outside the image | Low | Medium | Providers are operator-declared, never caller-influenced; note it, do not over-engineer |
| The guard is too strict and blocks a legitimate mount | Medium | Low | T4 pins the real route set; failure is loud and immediate at deploy |
| url4's resolver semantics drift from the engine's wrapper | Medium | Medium | T5's refactor note: wrap, do not reimplement |

## 7. Open questions

**OQ-2.1 — Does `[holdings]` visibility need a second control before an operator can
use it in production?** D8 accepts global shelves with a startup warning. If any
real deployment intends to put per-team content there, the warning is not enough and
per-caller scoping must move from "out of scope" to a blocking dependency on
`packages/url4`. Recommended default: ship as decided, and add a line to the
operator docs stating the constraint before the first non-empty `[holdings]`
declaration reaches a production values file.
