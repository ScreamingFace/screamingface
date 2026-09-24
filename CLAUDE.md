# CLAUDE.md — mandatory minimum

ScreamingFace: an open-source AI ensemble toolkit (Claude/Gemini/Codex/Ollama) that beats
single-model SOTA, runs locally, publishes to a public leaderboard. By OpenMined.

**The full guide — skills, agents, cards, process, product context, history:
`.claude/README.md`.** Repo routing: the `working-in-this-repo` skill.

## Monorepo

- `apps/aigateway` — LiteLLM-based AI gateway (Python, uv)
- `apps/scoreboard` — benchmark scoreboard + portal (Python, uv)
- `packages/` — shared libs (reserved; `url4-python-sdk` first)
- Public website lives in the separate `screamingface-web` repo; this monorepo does not
  publish GitHub Pages.
- `docs/` — SDLC artifacts: `spec/ plan/ tasks/ work/ diagrams/` (see `docs/README.md`)
- Legacy (desktop, server, url4 engine): tag `legacy-monorepo-2026-07-08` — read-only,
  never resurrect from it.

## AI SDLC — MANDATORY

Process: `task-management` skill + `sdlc-*` skills + cards `.claude/task-board.local.md` /
`.claude/sdlc.local.md`. Always:

0. **95% confidence gate — TOP RULE.** Below 95% confident it's correct AND wanted →
   STOP and ask. Applies to everything: code, work items, docs, diagrams.
1. **Epic first.** Every unit of work is a Linear issue under an epic (`OME-N`, Engineering
   team, 😱 ScreamingFace V1) with its labels (a **component/landing** label — `app/*`/`pkg/*`
   or `repo` — MANDATORY, no default; one `who-acts`; one `actor` — agentic|human, mandatory), a
   **self-assigned assignee** (`assignee: "me"` —
   mandatory on every issue and epic; nothing is filed unassigned), and a mirror in
   `docs/tasks/`. The issue is
   created when the PR is opened — not at work start, and not on a commit or a new branch —
   and only after you confirm it with the user. No fitting epic
   → the agent proposes one (stating plainly that it may not create an epic on the user's
   behalf) and, only with the user's direct consent, creates it in the Triage state with the
   rationale in the body and Irina plus Kevin tagged in a comment for scope approval; the leaf
   is then filed under it and the PR proceeds without blocking on that approval. Agents do not
   file orphan tickets and never auto-create epics. **The only exception to epic-first is a
   `bug`:** an issue labeled `bug` may be filed with no parent epic — in Triage, left
   unassigned, with Irina and Kevin tagged for review. Everything else goes under an epic and
   self-assigns.
   Every epic also carries exactly one **epic-classification** (`tech-debt`/`product-feature`/
   `infra` — the `epic` group's single-select leaves, and the epic marker); non-epics never carry
   it. `blocked` is applied only with a named blocking ticket/epic + a Linear blocked-by relation.
   Close status in BOTH Linear and the mirror at finish.
2. **Work ledger.** Every unit has `docs/work/YYYY-MM-DD-<slug>.md` (slug, not a ticket id —
   no `OME-N` exists until PR-open) — created at work START from `docs/work/TEMPLATE.md`,
   `ticket: unfiled` backfilled to `OME-N` at PR-open, outcome filled at finish.
3. **Spec before plan, plan before code.** `docs/spec/` then `docs/plan/` artifacts are
   hard prerequisites (superpowers brainstorming → writing-plans; scratch in gitignored
   `.docs/`). Implementation starts only on explicit approval in plain words.
4. **Diagrams** → `docs/diagrams/` (SVG + PNG); propose the diagramming plugin
   (https://github.com/sergio-bershadsky/ai/tree/main/plugins/diagramming) if absent.
5. **Worktree per unit — never edit in the shared checkout.** Always:
   ```sh
   git fetch origin
   git worktree add .claude/worktrees/<slug> -b <slug> origin/main
   ```
   Use the `<slug>` (branch description) at work start — no `OME-N` exists until PR-open. At
   PR-open, after filing the issue, rename the branch to `OME-N-<desc>` (`git branch -m`) so
   the branch-name GitHub/Linear automation links. Branch from **`origin/main`**, never from
   whatever happens to be checked out. Sessions run concurrently against one clone, and a
   branch switch **silently relocates uncommitted work** onto the new branch — this has
   already happened here (see `docs/work/2026-08-04-OME-743-*`). Remove with
   `git worktree remove` once merged.
6. **Branches/commits/PR.** Branch `<slug>` at work start, renamed to `OME-N-<desc>` at
   PR-open once the issue is filed; conventional commits; `Refs: OME-N` in the PR body (not
   required on commits); never `Co-Authored-By`; never commit to `main` (`.githooks/pre-commit`
   + protection). Every change lands via **PR** — green CI first, then squash-merge; never
   `--admin`.
7. **Asana is READ-ONLY** product/marketing input (`asana-product` skill). Technical work
   never goes to Asana.
8. **Cross-cutting** (≥2 apps/packages) → one sub-issue per affected app/package under the
   epic. Never one mega-ticket. Single-landing work is still a leaf under an epic.
9. **Linear via MCP only** (`/mcp` to activate). API tokens / raw GraphQL are forbidden;
   MCP-uncovered operations are owner actions in the Linear UI.

## Architecture — MANDATORY

- DRY · SOLID · hexagonal: core defines ports; plugins/adapters implement them; **core
  never imports plugins**; wiring via registry, not direct imports.
- AIGateway credentials: ORMStore/Tortoise `credential_blobs` only (AES-256-GCM via
  SecretStoreMixin); no OS keychain; `AIGATEWAY_SECRET_KEY` never stored or logged.

## Setup (one-time)

```sh
git config core.hooksPath .githooks
```
