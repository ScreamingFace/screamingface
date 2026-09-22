# Unit 1 — Shared world module and stateless handlers (F1 + F2)

**Depends on:** nothing. This is the first landing.
**Behaviour change:** none. That is the acceptance bar.
**Reviewable as:** a pure refactor.

## 1. User story

> As an engine developer, I want the world-building code to live in one place that
> both halves of the engine may import, and I want request-specific state to travel
> with the request rather than on a long-lived handler object, so that a single
> process can serve many callers from one world.

Nothing user-visible ships in this unit. It exists because units 2 and 3 are unsafe
without it, and because bundling it with them would make a regression impossible to
bisect. [`ans:Q7`]

## 2. What changes

### F1 — the `world` package

Move into `screamingface_engine/world/`:

- `build_aigateway_world` and the `_ModelEndpoint` handler (from `runner/connector.py`)
- the `_world()` factory (from `runner/main.py:266-348`)
- `world_config.py`, `models/`
- the benchmark, candidate-invocation and corrective-runtime installers

`world/` imports neither `runner` nor any control-plane module.
`.claude/scripts/check_layering.py` (repo root) gains a third category, `WORLD`,
importable by both halves and importing neither.

The doctrine sentence at `.claude/scripts/check_layering.py:87-91` changes from
*"the control plane never evaluates an expression in-process"* to *"the control
plane never runs an **ensemble** in-process"*. This is a deliberate, recorded change
of rule, not an exemption. The comment must say so, naming this document. [proposed]

### F2 — `request_scope`

Replace the per-run fields on `_ModelEndpoint` (`runner/connector.py:275-313`) —
identity headers, profile, cache policy, answer seed — with a `ContextVar` holding a
frozen `RequestScope` dataclass. Two producers:

| Producer | When | Source |
|---|---|---|
| Child process boot | once, at run start | environment (`job_env`) |
| Sync request (unit 3) | per request | verified headers |

The connector reads the ContextVar. It holds no caller state on `self`.

The engine already uses this pattern twice — `trace_scope.py` and `logs.py` both
bind a ContextVar for the duration of a run — so this is an existing idiom, not a
new one. [implied]

## 3. Acceptance criteria

### AC1 — the ensemble path is byte-for-byte unchanged (happy path)
> **Given** the existing test suite and conformance suite
> **When** unit 1 is applied
> **Then** every test passes without modification to its assertions
> **And** a golden url4 expression produces an identical result before and after.

Test-file moves are permitted. Assertion changes are not. An assertion that must
change is evidence of a behaviour change, and the change must be justified or
reverted. [proposed]

### AC2 — two concurrent callers never see each other's scope (concurrency)
> **Given** a single process holding one world
> **When** two requests run concurrently with different identities, profiles, seeds
>   and cache policies
> **Then** each outbound aigateway call carries exactly its own caller's values
> **And** neither request observes any value belonging to the other.

This is the defining requirement of the unit. Everything else is mechanical.

### AC3 — no caller state survives a request (structural)
> **Given** the refactored handler
> **When** a request completes
> **Then** no attribute on the handler, the world, or any module-level object holds
>   that request's identity, profile, seed or cache policy.

Enforced by an explicit test, not by review. A future contributor re-adding a cached
field is the realistic failure mode, and review does not reliably catch it.

### AC4 — spawned tasks inherit the scope (concurrency)
> **Given** a request whose execution spawns child tasks
> **When** a child task makes an aigateway call
> **Then** it observes the same scope as its parent
> **And** a sibling request's tasks observe a different one.

ContextVars are copied at task creation, so this should hold for free — which is
exactly why it needs a test. Free behaviour breaks silently when someone later
moves task creation outside the scope-bound region.

### AC5 — an unbound scope fails loudly (edge)
> **Given** code that reads `request_scope` with nothing bound
> **When** the read happens
> **Then** it raises a named engine error
> **And** it does not return a default-constructed scope.

A silent default would send an anonymous, unprofiled, unseeded call to aigateway and
bill someone for it. Failing loudly is the safe behaviour. [proposed]

### AC6 — the child still fills the scope from its environment (failure path)
> **Given** a child process started with the run's environment
> **When** the run begins
> **Then** the scope is bound from `job_env` before any handler executes
> **And** a missing required variable fails the run with its existing error code.

### AC7 — layering is enforced in CI (failure path)
> **Given** `check_layering.py` with the new `WORLD` category
> **When** `world/` imports from `runner/` or from a control-plane module
> **Then** the check fails with a message naming the offending import.

### AC8 — the control plane may import `world`, not `runner` (failure path)
> **Given** the updated rules
> **When** a control-plane module imports `runner`
> **Then** the check still fails
> **And** when it imports `world`, the check passes.

## 4. Out of scope

- Any new HTTP route, CLI mode or Deployment.
- Any change to `url4.toml` parsing. `[data]`, `[holdings]`, `[identities]` keep
  raising `WorldConfigError` until unit 2.
- Sharing one world across runs in local mode. The factory still builds per run
  here; unit 3 changes that.
- Removing the per-run world from the child. The child keeps building its own world,
  because its isolation model depends on it.

## 5. TDD plan

Ordered by risk, not by convenience. A silent cross-caller leak is the worst outcome
this unit can produce, so it is pinned first — before any code moves.

### T1 — concurrent scopes do not leak (AC2)
**RED** — With the *current* code, construct one handler and drive two concurrent
calls with different identities through it. Assert each outbound request carries its
own identity. This fails today, because the identity lives on `self`. That failure
is the proof the refactor is necessary, and it is the regression guard afterwards.
**GREEN** — Introduce `RequestScope` and the ContextVar. Read identity, profile,
seed and cache from it in `_headers()`.
**Refactor** — Strip the corresponding fields from the handler's `__init__`.

### T2 — no caller state on any long-lived object (AC3)
**RED** — After a request, assert the handler's `__dict__` and `__slots__` contain
none of the scope field names. Fails while the fields exist.
**GREEN** — Remove them.
**Refactor** — Freeze `RequestScope` with `@dataclass(frozen=True, slots=True)` so
it cannot be mutated in place and accidentally shared.

### T3 — unbound scope raises (AC5)
**RED** — Call `current_scope()` with nothing bound; expect a named error. Fails
while the ContextVar has a permissive default.
**GREEN** — Give the ContextVar no default and raise on lookup failure.
**Refactor** — Name the error alongside the engine's existing error types.

### T4 — spawned tasks inherit (AC4)
**RED** — Bind a scope, spawn a task, assert the task sees it; concurrently bind a
different scope in a sibling and assert isolation.
**GREEN** — Should pass once T1 is green. If it does not, task creation has escaped
the bound region, which is the bug this test exists to find.
**Refactor** — none expected.

### T5 — golden-output parity (AC1)
**RED** — Record the result of a fixed expression against a stubbed aigateway on the
pre-refactor tree; assert equality post-refactor. Written before the move so the
recorded value is genuinely the old behaviour.
**GREEN** — The move itself.
**Refactor** — Keep the golden as a permanent characterization test.

### T6 — child boot binds from environment (AC6)
**RED** — Start the run entry point with a prepared environment, assert the bound
scope matches. Fails before the producer exists.
**GREEN** — Bind the scope in the child's boot path.
**Refactor** — Share the header-parsing helpers with unit 3's producer.

### T7 — layering rules (AC7, AC8)
**RED** — Add fixtures: a `world` module importing `runner`, and a control-plane
module importing `world`. Assert the first fails and the second passes. Fails before
the `WORLD` category exists.
**GREEN** — Add the category and the rules.
**Refactor** — Update the rule's docstring to cite this document.

### T8 — the suite, unchanged
Not a new test. The gate: the full suite and the NATS conformance suite pass with no
assertion edits. Run before declaring the unit done.

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A hidden dependency on handler state changes answer determinism | Medium | High | T5 golden parity; `answer_seed` covered explicitly |
| Import cycle when splitting `world` out | Medium | Medium | `world` depends only on `packages/url4` and stdlib; T7 catches the rest |
| The layering change is read as permission to blur the halves | Low | High | The rule comment names this document and states the narrowed wording |
| A test-only import of `runner` from `world` slips in | Medium | Low | The layering check covers `src/`. Tests are not layered: a test may import both halves (`04-review-fixes.md` FX-71) |

## 7. Open questions

None. Everything in this unit was settled in the interview or is a pure engineering
choice recorded as `[proposed]` above.
