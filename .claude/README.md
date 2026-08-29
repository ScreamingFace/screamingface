# Claude in this repo — the guide

Everything Claude-related in `ScreamingFace/screamingface`: skills, agents, cards, scripts,
process, and the context that used to bloat `CLAUDE.md`. `CLAUDE.md` stays minimal and
mandatory; this file is the map.

## TL;DR — how a unit of work flows

```
Linear work item (OME-N, 😱 ScreamingFace V1)          ← task-management skill
  └─ mirror docs/tasks/YYYY-MM-DD-<name>.md
branch OME-N-<desc>
  └─ ledger docs/work/YYYY-MM-DD-OME-N-<desc>.md       ← created BEFORE any code (D8)
sdlc loop: FRAME → DESIGN → RED → GREEN → REFACTOR      ← sdlc-python / sdlc-electron
  → gates: uv run .claude/scripts/run_gates.py <stack>
commit "feat: …" + body "Refs: OME-N" → PR → review → squash-merge
close: Linear comment (close template) + state Done + mirror closed
```

## Skills (`.claude/skills/`)

| Skill | Invoke when | What it does |
|---|---|---|
| `task-management` | ANY ticket work — session start, before starting/filing/closing a work item | The Linear lifecycle: card resolution, label taxonomy, D9 cross-cutting rule, STOP labels, close discipline, MCP command crib, the Linear rich-text dialect |
| `sdlc-python` | EVERY Python change (apps/aigateway, apps/scoreboard, future pkg) | Rigid TDD loop: ledger-first → RED → GREEN → gates → wisdom → commit. Tortoise ORM work → `tortoise-dev` companion (mandatory) |
| `sdlc-electron` | EVERY Electron change (upcoming desktop app) | Same loop; Electron idiom: main/preload/renderer, both-side IPC contracts (S2), official security checklist encoded, a11y gate (S1) |
| `arch-electron` | DESIGNING/reviewing Electron architecture — app scaffold, extension platform, external-process integration, extension API changes | Binding invariants (VS Code model): manifest-first contributions, lazy activation, utilityProcess extension host, versioned injected API, disposables, core ProcessSupervisor, DEBUG-gated log view. Diagrams: `docs/diagrams/electron-*` |
| `arch-electron-layout` | DESIGNING/reviewing the desktop app's workbench layout — shell regions, view containers/slots, layout persistence, focus behavior | Binding L-rules: core-owned shell, views-in-containers, manifest placement = hint, user override wins & persists, no focus stealing, document-centric main area, per-window layout trees |
| `url4-engine` | DESIGNING/reviewing the url4 engine / AI-ensemble execution protocol — node resolution, WS(stream) vs HTTP-GET(transactional) transport, recursive fan-out/reduce DAG, telemetry forwarding | PROPOSED design-stage invariants: url4-expression-as-address, node-selects-transport, one trace_id/tree, cost.usage as a separate event, hybrid relay ↑ + Enclave store, RFC 8288 Link header. Diagrams: `docs/diagrams/ensemble-node-*` |
| `asana-product` | Reading product/marketing context from Asana | READ-ONLY. Never creates/updates in Asana; dev items link back via `asana_url` |
| `working-in-this-repo` | Starting any change; unsure where code goes / which CI / how to PR | The routing map: components, toolchains, CI lanes, release lanes, branch/PR rules |
| `screamingface-design` | Any UI/UX/visual/copy decision | The brand law (overrides shadcn/Tailwind defaults) |

Loop parity: the `SHARED-LOOP` regions of `sdlc-python` and `sdlc-electron` are
byte-identical — edit them TOGETHER, `repo-checks.yml` CI enforces it.

## Agents (`.claude/agents/`)

| Agent | Use |
|---|---|
| `sdlc-unit-executor` | Execute ONE `OME-N` work item end-to-end through the SDLC loop, autonomously. STOPs compile to `blocked ⛔`/`needs-owner` labels + comment. Batch: one executor per independent item; serialize same-stack items |
| `ticket-filer` | File an already-approved list of work items into Linear — mechanical only, all-or-nothing validation against the card (actor label mandatory) |

## Cards (committed repo config — the registries)

- **`.claude/task-board.local.md`** — Linear registry: team (Engineering/OME), project
  (😱 ScreamingFace V1), state IDs, every label ID, priority map, close template, ticket
  rules. **Card missing → HARD STOP** (restore from git).
- **`.claude/sdlc.local.md`** — stacks (aigateway, scoreboard → `sdlc-python`), their
  gates, `test_globs`, invariants, companion skills, `commit_refs`, `ledger_dir`.

## Scripts & CI (`.claude/scripts/`, `.github/workflows/repo-checks.yml`)

- `run_gates.py <stack>` — deterministic gate runner (append-only test check + the card's
  gates, first-red stops). Run from repo root: `uv run .claude/scripts/run_gates.py aigateway`.
- `check_loop_parity.py` — verifies the sdlc skills' SHARED-LOOP regions are identical.
- `repo-checks.yml` — runs parity on any `.claude/skills/sdlc-**` / `.claude/scripts/**` change.

## Linear — the work-item system (MCP ONLY)

- Transport: **the Linear MCP plugin only** (`/mcp` to activate). API tokens/GraphQL are
  forbidden; what MCP can't do (label/team/state admin) is an owner action in the Linear UI.
- IDs: `OME-N` (Engineering team, one sequence). Every item attaches to
  **😱 ScreamingFace V1** and carries: workstream (`Epic` group: url4 Engine, AI Gateway,
  Desktop App, Python SDK, Leaderboard, …) when applicable · landing (`app/aigateway`,
  `app/scoreboard`, `pkg/url4-python-sdk`, or `repo`) · one `who-acts`
  (design-session/autonomous/deferred) · **one `actor` (agentic|human — mandatory)**.
- Cross-cutting (≥2 app/pkg labels) → epic + one sub-issue per affected app/package.
- STOPs are labels (`blocked ⛔`, `needs-owner`) + a comment — never new states.
- Sprints = the project's milestones (S0–S5), owned by the project lead.

## docs/ — the artifact trail

`docs/spec/` (design before planning) → `docs/plan/` (plan before code) → `docs/tasks/`
(work-item mirrors) → `docs/work/` (ledgers, created at work START) → `docs/diagrams/`
(SVG + PNG). Local scratch: gitignored `.docs/`. See `docs/README.md`.

## Product context

- **ScreamingFace**: an open-source AI ensemble toolkit — combine models (Claude, Gemini,
  Codex, Ollama) to beat single-model SOTA, running locally on subscriptions users already
  pay for, scores tracked on a public leaderboard (screamingface.ai). Built by OpenMined.
- **Key concepts**: `url4` — DAG-based protocol encoding AI task chains as readable URLs ·
  **Enclave** — secure cloud runner + cache · **Ensemble** — multi-model > any single
  model · **SOTA** — the benchmark scores to beat.
- **App screens** (desktop): Settings (model connections) · Spend (usage/cost) ·
  Eval Studio (run benchmarks) · Cache/Log (query cache browser).
- **Team**: TBD — being reshuffled, to be settled in the next couple of days
  (2026-07-08). Linear project lead: Irina.

## History

- **Re-foundation (July 2026, SF-348/PR #371):** legacy `apps/desktop` + `apps/server`
  (and old docs/web/infra/personas) removed; full tree preserved read-only at tag
  **`legacy-monorepo-2026-07-08`** — never resurrect from it into the live tree. New
  desktop + CLI packages arrive as separate components once naming locks.
- **AI SDLC adoption (OME-358/PR #376):** everything this guide describes; decisions
  D1–D13 in `docs/spec/2026-07-08-ai-sdlc-adoption-spec.md`.
