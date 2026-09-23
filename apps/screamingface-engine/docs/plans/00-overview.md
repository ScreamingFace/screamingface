# Unifying the url4 surfaces — overview

**Status:** planning. No code, no Linear issue, no work ledger yet.
**Scope:** `apps/screamingface-engine`, plus read-only use of `packages/url4`.
**Authored:** 2026-09-22.

Source tags used throughout these documents:

| Tag | Meaning |
|---|---|
| `[stated prompt]` | The owner said this in the originating conversation. |
| `[stated ans:Qn]` | The owner chose this in an elicitation round. See §6. |
| `[implied]` | A necessary consequence of something stated. |
| `[proposed]` | An engineering decision made here. Not yet approved. |

---

## 1. The problem

The engine runs url4 expressions well. It runs them one way only: a caller mints a
token, attaches a WebSocket, starts a run, and the work executes in a forked child
process behind a NATS queue. That path is correct for heavy ensembles that take
minutes. It is wrong for a single model call that takes two seconds.

The engine also diverged from the `packages/url4` model while building that path.
Four divergences block a synchronous surface today.

| url4's model | What the engine does | Consequence |
|---|---|---|
| One long-lived `Url4Node` | World built **per run**, inside the child, then torn down (`runner/main.py:266-348`) | No live node exists for an HTTP request to reach. |
| Stateless handlers; caller data arrives with the request | One `_ModelEndpoint` holds per-run state: identity, profile, cache policy, answer seed (`runner/connector.py:275-313`) | A node shared by two callers would mix their state. |
| The node serves its own mounts over ASGI (`node.asgi()`) | The control plane may not evaluate anything (`check_layering.py:87-91`) | Serving mounts from the App is a doctrine change. |
| `url4.toml` registers data, holdings and identity routes | Those sections raise `WorldConfigError` (`world_config.py:252-259`) | Half of url4's mount vocabulary is switched off. |

## 2. The goal

Two surfaces over **one** world:

- **Ensemble surface** — unchanged. Token, WebSocket, `GET /?q=`, queue, worker,
  forked child, streamed frames. For heavy work. [implied]
- **Sync surface** — new. `GET /<mount>?q=(context)!intent`, one handler call, one
  response. For light work. [stated prompt]

Both must resolve the same mounts from the same declaration. That is the
unification. The surfaces differ in *transport and isolation*, never in *what is
addressable*.

## 3. Decisions that shape everything

| # | Decision | Source |
|---|---|---|
| D1 | The sync surface exposes **direct mounts only** (`GET /<mount>?q=`). The eval path (`/v1?q=<expression>`) is not part of the public sync surface in v1. No async hand-off. | `ans:Q1` |
| D2 | `[data]`, `[holdings]` and `[identities]` become real in v1. `[commands]` does not. Command-backed `[data]` providers are rejected. | `ans:Q2` |
| D3 | The node keeps url4's default `eval_path="/v1"`. Collisions are resolved by **route precedence** — engine literal routes are registered first and win. | `ans:Q3` |
| D4 | The sync surface requires **edge-verified identity only** (`X-User-Email`). No capability token. | `ans:Q4` |
| D5 | Sync budget: **30 s** per request, in-flight cap of **2× worker count**. | `ans:Q5` |
| D6 | The App **forwards verbatim** to the node Service. One public origin. | `ans:Q6` |
| D7 | Delivery is **three stacked units**. | `ans:Q7` |
| D8 | `[holdings]` and `[identities]` are operator-owned and **global to all sync callers** in v1. No per-caller scoping. No secrets in them. | `ans:Q9` |
| D9 | A sync response over **512 KiB** spills to the artifact store and the caller is **redirected**. | `ans:Q10` |

D1 is the most load-bearing decision, and it is worth stating why. A direct mount hit
in url4 does **not** parse the grammar and does **not** build a DAG
(`peer/_dispatch.py:123-146`). It decodes the wire envelope and calls one handler.
So the sync tier cannot fan out, cannot recurse, and cannot resolve a URL-valued
context. Three whole classes of risk — unbounded concurrency, unbounded depth, and
server-side request forgery — are removed by the choice of surface rather than by a
guard that could be misconfigured. [implied]

D3 inverts a risk. Because precedence is now the collision mechanism, the startup
collision check (F4) stops being a nicety and becomes the thing that prevents a
silently shadowed mount. It must **fail startup**, not warn. [implied]

## 4. Architecture

### 4.1 Foundation — the four refactors

These are shared by both deployment shapes. They are the actual unification; the
shapes only decide where the node runs.

- **F1 — one `world` package.** Move `build_aigateway_world`, the `_world()`
  factory, `world_config`, `models/*`, and the benchmark, candidate and corrective
  installers out of `runner/` into `screamingface_engine/world/`. It imports
  neither `runner` nor the control plane. `check_layering.py` gains a third
  category, `WORLD`, importable by both halves.
- **F2 — stateless handlers.** Replace per-run fields on `_ModelEndpoint` with a
  `request_scope` ContextVar. Two producers fill it: the child at boot from its
  environment, and the sync layer per request from headers. The connector reads one
  place.
- **F3 — real config sections.** Delegate `[data]`, `[holdings]` and `[identities]`
  to url4's own resolvers, registered on the same node.
- **F4 — mount collision guard.** At startup, check node mounts against engine
  literal routes and against each other. Fail on collision.

F2 is the change that turns "a world per run" into "a world per process". Without
it, nothing else is safe. [implied]

### 4.2 Deployed shape — a node tier

```
          ┌──────────────┐
client ──▶│  App (1×)    │──── ensemble ───▶ NATS ──▶ worker pool (N×)
          │ control plane│                              │ fork
          │  auth, ident │                              ▼
          └──────┬───────┘                          child proc
                 │ sync, verbatim                   (own world)
                 ▼
          ┌──────────────┐
          │  Node tier   │──────────────────▶ aigateway
          │  (N×, stateless)                  Tavily, S3
          └──────────────┘
```

The node tier is a new Deployment running `screamingface-engine node`. It builds the
world once and serves `node.asgi()` wrapped in url4's own admission and timeout
guards (`cli/_serve.py:265-305`). It is stateless, horizontally scalable, and
reachable only from the App. [stated prompt, `ans:Q6`]

### 4.3 Local shape — the node inside the App

`serve --local` mounts the same `node.asgi()` inside the App, registered last so
engine literal routes win (D3). The in-process run path shares that one node as its
`IOLayer`. One codebase, two placements; only the composition root differs.
[stated prompt]

## 5. Delivery units

| Unit | Contents | Proves it works by | PRD |
|---|---|---|---|
| 1 | F1 + F2 | The existing suite stays green. Zero behaviour change. | `prd/01-foundation-world-module.md` |
| 2 | F3 + F4 | New config sections resolve; collisions fail startup. | `prd/02-config-and-mount-guard.md` |
| 3 | Node tier, sync surface, App forwarder, local mount, Helm | A curl against a mount returns a model answer. | `prd/03-node-tier-and-sync-surface.md` |

Each unit is independently revertible. Unit 1 is a pure refactor and should be
reviewed as one. [`ans:Q7`]

## 6. Interview record

| Id | Question | Answer |
|---|---|---|
| Q1 | Which url4 surfaces are synchronous in v1? | Direct mounts only |
| Q2 | Which reserved `url4.toml` sections land in v1? | `[data]` + `[holdings]` + `[identities]` |
| Q3 | How to resolve the `eval_path` `/v1` collision? | Keep `/v1`, rely on route precedence |
| Q4 | What does the sync surface require from a caller? | Edge identity only |
| Q5 | Sync timeout and in-flight budget? | 30 s, in-flight 2× workers |
| Q6 | How is the node tier reached? | App forwards verbatim |
| Q7 | How is the work sliced? | Three stacked units |
| Q8 | Where do the documents live? | `docs/plans/` (planner default) |
| Q9 | Holdings and identities on a shared tier? | Global, documented, no secrets |
| Q10 | What does a large sync response do? | Cap at 512 KiB, spill to S3, redirect |

Two answers went against the recommendation here, and both change the design rather
than merely selecting it:

- **Q5 (30 s).** Reasoning models routinely exceed 30 s. The sync surface is
  therefore for *fast* calls only, and its 504 body must name the ensemble path as
  the remedy. Tracked as a risk in `test-plan.md` §2 R7.
- **Q10 (spill, not reject).** This pulls the artifact writer and S3 credentials
  into the node tier, and it exposes a gap: `GET /artifacts/{id}` requires a
  capability token today, which a sync caller never has (D4). See
  `contracts.md` C6.

## 7. Reading order

1. This file.
2. `erd.md` — what the entities are and where they live.
3. `contracts.md` — every hop, its shape, and its failure behaviour.
4. `prd/01` → `prd/02` → `prd/03` — the units, in build order.
5. `test-plan.md` — the risk model and what is deliberately not tested.

## 8. Out of scope for v1

- The eval path as a public sync surface, and any async hand-off between surfaces. [`ans:Q1`]
- `[commands]` exec mounts. [`ans:Q2`]
- Per-caller scoping of holdings and identities. [`ans:Q9`]
- Mount-table federation, `.well-known/url4-*` documents, and cross-origin
  forwarding (OME-1183 / OME-1187). The node tier is the right home for these and
  should host them next, but nothing here depends on them. [proposed]
- Any change to the ensemble path's behaviour. It is regression surface only.
