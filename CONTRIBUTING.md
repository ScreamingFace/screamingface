# Contributing to ScreamingFace

This guide covers running the repo's code from source and the git workflow.

> The legacy desktop app and plugin server were removed in the July 2026 re-foundation (tag
> `legacy-monorepo-2026-07-08`). The stacks below are the active codebase; new desktop/CLI
> packages will arrive with their own guides. The public website lives in the separate
> `screamingface-web` repo — it is not part of this monorepo.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| uv | latest | Python toolchain/installer. `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | ≥ 3.12 | `uv` installs and pins this for you; no system Python needed. |
| Node | 22 | Only for the `aigateway-ui` stack. Version pinned in `apps/aigateway-ui/.nvmrc` (`nvm use`); npm ships with it. |

## Get the code

```bash
git clone https://github.com/ScreamingFace/screamingface.git
cd screamingface
git config core.hooksPath .githooks   # enables the pre-commit guard (blocks commits to main)
```

## Stacks

The repo is organised as **stacks**, not just apps — each is self-contained with its own
manifest, lockfile, tests, and README. The stack name is what the tooling takes.

| Stack | Root | What it is |
|---|---|---|
| `aigateway` | `apps/aigateway` | LiteLLM-based AI Gateway — provider OAuth, encrypted credential store (service, port 9105) |
| `aigateway-ui` | `apps/aigateway-ui` | Admin console for gateway accounts and their provider API keys (Next.js service, port 9107) |
| `scoreboard` | `apps/scoreboard` | Public benchmark scoreboard + demo portal (service, port 9106) |
| `screamingface-engine` | `apps/screamingface-engine` | Single-process REST + WebSocket url4 execution app (service, port 9108) |
| `report-intake` | `apps/report-intake` | Accepts a client error report and files it into the private tracker (service, port 9109) |
| `url4` | `packages/url4` | url4 expression protocol — grammar, parser, AST, interpreter (library) |
| `screamingface` | `packages/screamingface` | Public Python Client SDK for Engine-owned benchmark evaluation (library) |

Every stack but `aigateway-ui` is Python + uv; `aigateway-ui` is TypeScript + npm. The runner
below takes either — it reads each stack's gate list from the card rather than assuming a
toolchain.

The canonical list lives in [`.claude/sdlc.local.md`](.claude/sdlc.local.md).

## Run from source

```bash
# AI Gateway — provider OAuth, encrypted credential store (port 9105)
cd apps/aigateway
uv sync
uv run uvicorn aigateway.main:app --port 9105 --reload
curl -sf http://localhost:9105/healthz   # liveness check

# aigateway-ui — admin console for accounts + provider API keys (port 9107)
# Needs a reachable aigateway; it calls the admin API server-side and never from the browser.
cd apps/aigateway-ui
nvm use && npm ci
AIGATEWAY_ADMIN_BASE_URL=http://localhost:9105 npm run dev
curl -sf http://localhost:9107/healthz   # liveness check

# Scoreboard — public benchmark scoreboard + demo portal (port 9106)
cd apps/scoreboard
uv sync
uv run scoreboard

# report-intake — accepts a client error report and files it (port 9109)
cd apps/report-intake
uv sync
uv run report-intake
curl -sf http://localhost:9109/healthz   # liveness check

# url4 — a library, not a service
cd packages/url4
uv sync

# screamingface — Client SDK + deterministic example notebooks
cd packages/screamingface
uv sync --extra notebook
```

## Tests, lint, typecheck

**One command per stack — the gates CI runs, in CI's order, plus one CI doesn't:**

```bash
uv run .claude/scripts/run_gates.py <stack>   # aigateway | aigateway-ui | scoreboard | report-intake | url4 | screamingface-engine | screamingface
```

It resolves the stack from [`.claude/sdlc.local.md`](.claude/sdlc.local.md), runs its gates
from the stack root, and stops at the first failure:

```
✓ append-only test check (vs HEAD)
✓ uv run ruff check                                    # lint
✓ uv run ruff format --check                           # formatting
✓ uv run pyright                                       # typecheck
✓ uv run pytest --cov=<stack> --cov-fail-under=<N> -q  # tests + coverage floor
ALL GATES GREEN
```

Coverage floors differ by stack (`url4` is 95, the services are 80) — another reason to use
the runner rather than reconstructing the command by hand.

The `screamingface` lane also regenerates/checks notebooks, builds the wheel and sdist, and
verifies their contents. These are part of its CI contract, not optional documentation checks.

`aigateway-ui` runs a different gate list for the same reasons, and the runner knows it:

```
✓ npm ci            # install FROM the lockfile; fails if package.json disagrees
✓ npm run lint      # eslint
✓ npm run typecheck # tsc --noEmit
✓ npm run test:ci   # vitest + coverage floor 80
ALL GATES GREEN
```

The **append-only check** is the runner's own — CI does not run it. It guards prior tests from
being edited or deleted, so a change can't quietly weaken the suite it inherited. If you
genuinely must change an existing test, that's a deliberate call to raise in review, not a gate
to route around — `--skip-append-only` exists for that conversation, and skipping it belongs in
your PR description. Everything else matches CI step for step
(`aigateway-tests.yml`, `scoreboard-tests.yml`, `url4-tests.yml`, `screamingface-engine-tests.yml`,
`screamingface-tests.yml`).

An unknown stack fails fast and tells you the real ones:

```
CONFIG ERROR: stack 'docs' not in .claude/sdlc.local.md (has: aigateway, scoreboard, report-intake, url4, screamingface, screamingface-engine, aigateway-ui)
```

Docs-only changes (`README`, `CONTRIBUTING`, `docs/`) have no stack and no CI — there is
nothing to run.

Stack-specific:

- `apps/aigateway` live tests (`-m live`, real provider OAuth) are skipped in CI. Run them
  locally, with backends actually connected, before asking to merge changes that touch the
  gateway request/refresh path.
- Never import `litellm-enterprise` — the aigateway gates run
  `scripts/check_no_enterprise.py` as a guard.
- `packages/screamingface` notebooks are generated artifacts. Edit their builder cells, then run
  `scripts/check_notebooks.py`; do not commit kernel state, outputs, or hand-edited notebook drift.

## Git workflow

- **Work item first.** Every unit of work is a Linear issue (`OME-N`) in the **Engineering**
  team under the **😱 ScreamingFace V1** project. File it before you start.
- **Label it** (the board relies on these — see the table below).
- **Branch naming:** `OME-N-<description>` (e.g. `OME-12-fix-refresh`), where `N` is the
  Linear work-item number. Branch from `main`; this repo squash-merges, so don't stack PRs.
- **Never commit directly to `main`.** The `.githooks/pre-commit` hook (enabled above) blocks
  it; branch protection enforces it remotely.
- **Conventional commits.** Use `feat:`, `fix:`, `docs:`, `chore:` etc. — release-please
  derives version bumps and changelogs from them (`feat:` → minor, `fix:` → patch;
  `docs:`/`chore:` don't bump). The body carries `Refs: OME-N`.
- **PRs:** squash-merge after review approval + green required checks. Include the Linear
  work-item link, a summary, and a test plan in the body.
- **Architecture is enforced.** DRY/SOLID/hexagonal are mandatory — see the "Architecture"
  section of [`CLAUDE.md`](CLAUDE.md).

### Labels when filing from the Linear UI

| Group | Rule | Values |
|---|---|---|
| Landing | one, required — where the work lands | `app/aigateway` · `app/scoreboard` · `pkg/url4-python-sdk` · `repo` (process/repo work) |
| `who-acts` | one, required | `autonomous` (runnable end-to-end) · `design-session` (needs a direction call first) · `deferred` (gated on a named precondition) |
| `actor` | one, **mandatory** — who executes | `human` · `agentic` |
| Type | optional | `Bug` · `Feature` · `Improvement` |

Work touching **two or more** `app/*`/`pkg/*` landings is cross-cutting: file a parent epic
plus one sub-issue per affected stack, rather than a single mega-issue.

If you're blocked mid-flight, add `blocked ⛔` (a hard question) or `needs-owner` (a decision
or visual check) and comment the exact question — leave the issue In Progress.

### Working with agents

Agent-executed work carries extra discipline — `docs/tasks/` mirrors, `docs/work/` ledgers,
and spec/plan artifacts under `docs/`. **That chain is agent discipline; it does not bind
human contributors.** As a human, the list above is the whole contract: issue → branch →
conventional commits → PR. The agent contract is documented in
[`.claude/README.md`](.claude/README.md).

## Pull-request Preview environments

A same-repository pull request receives a Preview only when it changes a deployable runtime.
The automation builds only affected images. Engine changes also build the Engine benchmark image.

The maintained `Preview` pull-request comment shows the current state and exact revision.
It also shows application links, Kubernetes commands, and SigNoz links after admission.

Preview states use these labels:

- `preview-building`: Required images are not ready.
- `preview-queued`: Images are ready, and the request waits for a slot.
- `preview`: Argo CD deploys the request.
- `preview-expired`: The 72-hour active period ended.
- `no-preview`: The author disabled the Preview.

Only three Preview environments can be active. The oldest ready request receives the next slot.
Close the pull request to delete its Preview. Pull-request code receives no Kubernetes credential.

## Releases

| Stack | How |
|---|---|
| `apps/aigateway` | release-please manages the release PR; merging it tags `aigateway-v*`, which builds the GHCR image + Helm chart (`release-aigateway.yml`). |
| `apps/aigateway-ui` | release-please manages the release PR; merging it tags `aigateway-ui-v*`, which builds the multi-arch GHCR image + Helm chart (`release-aigateway-ui.yml`). Unlike aigateway it is **not** mirrored to the public `sf-installer` repo — the console is internal operator tooling, not part of a product install. |
| `apps/scoreboard` | manual tag `scoreboard-v*` triggers `release-scoreboard.yml` (GHCR image + Helm chart). |
| `apps/report-intake` | release-please manages the release PR; merging it tags `report-intake-v*`, which builds the multi-arch GHCR image + Helm chart (`release-report-intake.yml`). Like aigateway-ui it is **not** mirrored to the public `sf-installer` repo — this is a service the team deploys, not part of a product install. Every PR also builds and starts the image (`report-intake-tests.yml`), which is what the other Python apps lack. |
| `packages/url4` | tag `url4-v*` triggers `release-url4.yml` — verify + build + `twine check`, then publish via PyPI Trusted Publishing. The publish step needs a one-time owner setup (PyPI project + Trusted Publisher + the `pypi` GitHub Environment); until that lands, verify and build still run and only publish fails. See the workflow header. |
| `packages/screamingface` | tag `screamingface-v*` triggers `release-screamingface.yml` — verify + build + distribution check + `twine check`, then publish via PyPI Trusted Publishing. Needs the same one-time owner setup as url4 (PyPI project + Trusted Publisher + the `pypi` GitHub Environment); the `screamingface` name is **not reserved on PyPI yet**. Until that lands, verify and build still run and only publish fails. |

## Reference

- **Repo guide** (skills, agents, cards, process, product context, history):
  [`.claude/README.md`](.claude/README.md) — start here
- **Repo routing** (which stack, which CI, who reviews): the `working-in-this-repo` skill
  (`.claude/skills/working-in-this-repo/`)
- **SDLC artifacts:** [`docs/README.md`](docs/README.md)
- **Gateway internals:** [`apps/aigateway/README.md`](apps/aigateway/README.md) (credential
  store, secret key, migrations)
- **Scoreboard internals:** [`apps/scoreboard/README.md`](apps/scoreboard/README.md) (portal,
  public artifacts)
- **report-intake internals:** [`apps/report-intake/README.md`](apps/report-intake/README.md)
  (the environment contract, the probe invariants) and
  [`charts/report-intake/README.md`](apps/report-intake/charts/report-intake/README.md)
  (the two-hostname edge, and what the chart refuses to render)
- **url4 SDK:** [`packages/url4/README.md`](packages/url4/README.md)
- **ScreamingFace Client SDK:** [`packages/screamingface/README.md`](packages/screamingface/README.md)
- **Legacy reference:** `git checkout legacy-monorepo-2026-07-08`
