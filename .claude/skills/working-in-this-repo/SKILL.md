---
description: How to work in the ScreamingFace monorepo — which app/component a change belongs to, the per-stack toolchain, how to add a new app or shared package, which CI runs, who reviews, and the branch/commit/PR/merge/release rules. Use when starting any change here, when unsure where code goes, which tests or CI apply, who reviews, or how to open and merge a PR.
user_invocable: true
---

# Working in this repo

ScreamingFace is a **polyglot monorepo** worked on by multiple developers concurrently. This skill is the **routing map**: given a change, it tells you which component you're in, the toolchain, the CI that will gate it, who reviews, and the branch/PR/release lane.

> **Re-foundation (July 2026).** The legacy `apps/desktop` and `apps/server` (plus `web/`, `infra/`, root `Makefile`, and the old `docs/` tree) were removed; the full pre-teardown state is preserved at tag **`legacy-monorepo-2026-07-08`**. The URL4 protocol and ScreamingFace Client SDK now live as separately gated packages. Setup lives in **`CONTRIBUTING.md`**; per-app guardrails in each app's `CLAUDE.md`.

> **`apps/desktop` still exists on disk and is NOT a component.** Its only tracked files are two build artifacts, `out/main/index.js` and `out/preload/index.js`, left behind by that teardown, and a `release-desktop.yml` workflow survives alongside them. Nothing imports either. Do not treat the directory as a live app or resurrect from it; removing the leftovers is an owner decision, not a routing question (noted 2026-09-22, `OME-1266`).

## 1. Component taxonomy

- **`apps/<name>`** — an independently deployable service or app. Has its own toolchain, lockfile, CI workflow, and release lane.
- **`packages/<name>`** — a shared library; **not** independently deployed. Put shared code here instead of importing one app's internals from another.
- **`docs/`** — AI-agentic decision records (plans, specs). Not a deployable component.

**Rule:** apps never import another app's internals. Cross-app sharing goes through `packages/` (or a stable HTTP contract). This keeps each app independently testable and releasable.

## 2. Current components — the routing table

| Component | Landing label | Stack | Run / test / lint / typecheck | Gating CI | Release lane | Key guardrails |
|---|---|---|---|---|---|---|
| `apps/aigateway` | `aigateway` | Python · uv · FastAPI (LiteLLM) | `uv run uvicorn aigateway.main:app --port 9105` · `uv run pytest` (live tests opt-in) · `uv run ruff check` · `uv run pyright` | `aigateway-tests.yml` (matrix 3.12/3.13) | release-please → `aigateway-v*` → `release-aigateway.yml` (GHCR image + Helm chart). Merges to `main` also build a dev image via `dev-build-aigateway.yml` (GHCR + ACR, `main-<sha>`) | **Never import `litellm-enterprise`** (guarded by `scripts/check_no_enterprise.py`). Credentials via ORMStore/Tortoise `credential_blobs`, **no OS keychain**; secrets AES-256-GCM; master key `AIGATEWAY_SECRET_KEY` never stored/logged. See `apps/aigateway/CLAUDE.md`. |
| `apps/aigateway-ui` | `aigateway` | **TypeScript · npm · Next.js** | `npm run dev` (port 9107) · `npm run test:ci` · `npm run lint` · `npm run typecheck` | `aigateway-ui-tests.yml` + `charts.yml` | release-please `node` → `aigateway-ui-v*` → `release-aigateway-ui.yml` (GHCR image + Helm chart; **no** `sf-installer` mirror — internal tooling, not a product install). Merges to `main` also build a dev image via `dev-build-aigateway-ui.yml` (GHCR + ACR, `main-<sha>`) | The repo's only **npm** stack (scoreboard uses Node for tests, but ships no package.json). It is a **BFF**: every call to aigateway's `/v1/admin` surface happens server-side (`output: "standalone"`, never `"export"`), so the browser never holds the admin API's address. UI code holds **no** copy of the admin allowlist — aigateway is the sole authority. Brand law is the **OpenMined Design System** vendored at `src/brand/tokens/` (NOT the `screamingface-design` skill — this is internal operator tooling wearing the parent brand); raw colors fail CI via `npm run lint:css`. |
| `apps/scoreboard` | `scoreboard` | Python · uv · FastAPI **+ Node for the portal tests** | `uv run scoreboard` · `uv run pytest` · `uv run ruff check` · `uv run pyright` · `node --test tests/portal/leaderboard-logic.test.js tests/portal/pareto-chart.test.js tests/portal/pareto-chart-review.test.js` | `scoreboard-tests.yml` | release-please → `scoreboard-v*` → `release-scoreboard.yml` (GHCR image + Helm). Merges to `main` also build a dev image via `dev-build-scoreboard.yml` (GHCR + ACR, `main-<sha>`), which the platform team auto-deploys to `leaderboard.dev.screamingface.ai` | Portal assets and public eval artifacts are app-local (`portal/`, `artifacts/`) — they ship inside the image. **The portal's pure logic is tested under Node's built-in runner**, so this stack's gates need a local Node (CI pins 24). No `package.json`, no lockfile, no npm ecosystem — Node is the whole harness (OME-798). |
| `apps/screamingface-engine` | `screamingface-engine` | Python · uv · FastAPI | `uv run screamingface-engine serve --local` · `uv run pytest` · `uv run ruff check` · `uv run pyright` | `screamingface-engine-tests.yml` | release-please → `screamingface-engine-v*` → `release-screamingface-engine.yml` (runtime + benchmark images). Merges to `main` also build a dev image via `dev-build-screamingface-engine.yml` (GHCR + ACR, `main-<sha>`), auto-deployed to `fusion.dev.screamingface.ai` | Owns deployed execution and Engine benchmark resources; cross-app integrations use stable HTTP/URL4 contracts. |
| `apps/report-intake` | `report-intake` | Python · uv · FastAPI | `uv run report-intake` (port 9109) · `uv run pytest` · `uv run ruff check` · `uv run pyright` | `report-intake-tests.yml` (matrix 3.12/3.13, **plus an image job that builds the container and starts it**) + `charts.yml` | release-please → `report-intake-v*` → `release-report-intake.yml` (GHCR image + Helm chart; **no** `sf-installer` mirror — infrastructure the team runs, not a product install). Merges to `main` also build a dev image via `dev-build-report-intake.yml` (GHCR + ACR, `main-<sha>`). Install runbook: `apps/report-intake/DEPLOYMENT.md` | `Settings` (`env_prefix="REPORT_INTAKE_"`) is the **sole authority** on this service's environment — `create_app` refuses to start on a `REPORT_INTAKE_*` name matching no field, because `extra="ignore"` would otherwise run the pod on the default. `FORWARDED_ALLOW_IPS` is the one variable it cares about that is *not* a field (it is uvicorn's) and must stay disjoint from `REPORT_INTAKE_ALLOWED_NETWORKS`. `/healthz` never grows a storage import and never sits behind an auth check; `/readyz` is the one that may fail closed, answers from `app.state.readiness_check`, and there is exactly one of it. Prompt-bearing content is **rejected**, never stored; nothing is ever authorized by `trace_id`/`run_id`; `X-User-Email` is named in exactly one module. |
| `apps/analytics` | `analytics` | Python · uv · FastAPI | `uv sync --frozen` then `uv run sf-analytics` (loopback 9110; the container binds 0.0.0.0:9110) · `uv run pytest` · `uv run ruff check` · `uv run pyright` | `analytics-tests.yml` | **Not in release-please and no tagged release lane.** Merges to `main` build a dev image via `dev-build-analytics.yml` (GHCR + ACR, `main-<sha>`) — that image is the only artifact it produces | Opt-in SDK event ingestion forwarded to PostHog, per `docs/spec/2026-09-09-OME-1152-analytics-service-spec.md`. It stores **no** prompts, cookies, identity links or database, and ships no SDK instrumentation. Port 9110 is an internal default, not a reserved public endpoint. |
| `apps/screamingface-studio` | — (no landing label yet) | **Three stacks in one Tauri app**: `frontend/` TypeScript · npm · `runtime/` Python · uv · `src-tauri/` Rust · cargo | per sub-directory; see each one's README | **None — no workflow gates this path.** | **Not in release-please and no release workflow.** | Newest component and the least wired-in: 97 tracked files, a CODEOWNERS entry, and no CI. Treat the absence of a gate as a gap rather than a decision, and confirm with the owner before assuming a change here is unchecked. |
| `packages/url4` | `url4-sdk` | Python · uv · library | `uv run pytest` · `uv run ruff check` · `uv run pyright` | `url4-tests.yml` | release-please → `url4-v*` → `release-url4.yml` (PyPI, Trusted Publishing) | Protocol, parser, AST, and abstract streaming boundaries stay free of concrete app adapters. |
| `packages/screamingface` | `client-sf` | Python · uv · Client SDK | `uv run pytest` · deterministic notebook check · `uv build` · distribution check | `screamingface-tests.yml` | release-please → `screamingface-v*` → `release-screamingface.yml` (PyPI, Trusted Publishing) | The Client links Candidates into Engine-owned Benchmark URL4; it does not implement benchmark protocols. Generated notebooks must remain output-free and deterministic. |

**Dev environment.** Every `dev-build-*.yml` fires on merge to `main` (path-filtered) and pushes the same shape: `ghcr.io/screamingface/<image>:main-<shortsha>` plus two `acropenmined.azurecr.io` tags. **Nothing here deploys production** — the platform team picks up the new dev image and deploys it (OME-730). The shared dev endpoints are `https://leaderboard.dev.screamingface.ai` (scoreboard) and `https://fusion.dev.screamingface.ai` (engine); both were live when this was written, 2026-09-22. The `nip.io` hostnames in the `DEPLOYMENT.md` runbooks are **examples** for a throwaway k3s smoke test, not this environment.

**Owner / reviewer per path:** see `.github/CODEOWNERS`. This skill deliberately does not hardcode owners — read them from one place.

## 3. Which CI runs on my PR?

CI is **path-filtered**: a PR only triggers the workflow(s) for the paths it touches. A PR touching two apps runs both lanes. Each `<component>-tests.yml` also self-triggers when its own YAML changes.

**Helm charts are gated separately** by `charts.yml`, filtered on `apps/*/charts/**`. It is its own workflow because `paths:` is workflow-level — a chart job inside an app's lane would run that app's whole test suite on every chart edit — and because its checks are about the **pair** of charts (the console must point at the Service the gateway renders; the gateway must admit the label the console's Pods carry), which neither app's lane owns. It runs `.github/scripts/verify_chart_wiring.py`, which renders and asserts on parsed YAML. `helm lint` alone is not a gate: it reports "0 chart(s) failed" for a chart that cannot render at all.

## 4. Adding a new component (any stack: Python / Go / JS / TS)

Bring whatever stack fits; satisfy this **invariant contract** so the coordination machinery sees it:

| Stack | Pkg manager | Layout | Lint | Typecheck | Test | CI: copy from | Release |
|---|---|---|---|---|---|---|---|
| Python | uv + hatchling | `src/<pkg>/` | ruff | pyright | pytest (+ markers) | `aigateway-tests.yml` | release-please `python`, or manual tag |
| JS / TS | npm | `src/` | eslint | `tsc --noEmit` | vitest | new `<comp>-tests.yml` (mirror the aigateway structure) | release-please `node`, or manual tag |
| Go | go modules | `cmd/` + `internal/` / `pkg/` | golangci-lint | `go vet` / build | `go test ./...` | new `go-<comp>-tests.yml` | release-please `go`, or manual tag |

**6-step checklist for a new component:**
1. Pick `apps/` (deployable) or `packages/` (shared lib).
2. Self-contained toolchain + lockfile; no dependency on another app's internals.
3. Add a path-filtered `.github/workflows/<component>-tests.yml` running that stack's lint + typecheck + test.
4. Register a release lane — add to `release-please-config.json` **or** document a manual tag (or mark "not released").
5. Add a `.github/CODEOWNERS` entry.
6. Add the matching `dependabot.yml` ecosystem (`uv` / `npm` / `gomod`).

## 5. Where does my change belong?

- **`apps/aigateway`:** new providers/secrets backends implement the port and register in the factory — never edit ORMStore. See `apps/aigateway/CLAUDE.md`.
- **`apps/scoreboard`:** portal/static changes live in `apps/scoreboard/portal/`; public artifact allowlists in `src/scoreboard/portal.py`.
- **`apps/screamingface-engine`:** deployed execution, benchmark resources, and Engine REST/WS contracts.
- **`apps/report-intake`:** client error reports — the wire schema and its caps, classification, storage, and the `TicketSink` port. A new environment variable is a `Settings` field first; the chart renders that set and nothing else.
- **`packages/url4`:** expression grammar, AST, interpreter, and abstract streaming protocol.
- **`packages/screamingface`:** public Client SDK, report models, UI/progress adapters, and generated examples; benchmark protocol logic remains Engine-owned.
- **Shared logic used by ≥2 apps:** it belongs in `packages/`, not copied.

## 6. Branch / commit / PR / merge

- **Branch:** `<slug>` at work start (no `OME-N` until PR-open), renamed to `OME-N-<description>` at PR-open after the issue is filed per the `task-management` skill (registry `.claude/task-board.local.md`) — the rename lets the branch-name automation link. Never commit to `main`.
- **Commit:** conventional (`feat: …`, `fix: …`); `Refs: OME-N` goes in the PR body (commits need no ticket); **no `Co-Authored-By`** lines.
- **Keep current:** rebase on `origin/main` (don't merge `main` into your branch); force-push only your own branch.
- **Merge:** squash-merge; the author merges after review approval + green required checks.
- **Checks are path-dependent.** Live tests (`AIGW_LIVE=1`) are opt-in diagnostics, **not** merge gates.
- **WIP limit:** 2 tickets per dev (one coding, one in review).
- **PR body:** Asana link · summary · test plan · screenshots for UI. If a PR spans two owners' areas, state the cross-service contract in the body.

## 7. Pointers (single source of truth)

- **Setup / run-from-source:** `CONTRIBUTING.md`
- **Per-app guardrails:** `apps/*/CLAUDE.md`
- **Work items / ticket lifecycle:** the `task-management` skill + `.claude/task-board.local.md`
- **Per-stack dev loop:** the `sdlc-python` / `sdlc-electron` skills + `.claude/sdlc.local.md`
- **Decision records & SDLC artifacts:** `docs/` (see `docs/README.md`)
- **Brand / UI law:** the `screamingface-design` skill
- **Legacy reference (desktop, server, url4 engine, web, infra):** tag `legacy-monorepo-2026-07-08`
