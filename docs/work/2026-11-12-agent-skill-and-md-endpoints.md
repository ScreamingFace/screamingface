---
ticket: OME-1894
stack: repo
status: in_progress
started: 2026-11-12
finished:
---

# agent-skill-and-md-endpoints: Experience using SF with Claude Code / Codex is good

## Intent

Publish a `screamingface` agent skill and plain-text docs endpoints, both generated from the ScreamingFace Client docs, so a coding agent installs the skill with one prompt and reads any docs page as Markdown.

## Planned changes

- `public-docs/agent-skill/skills/screamingface/SKILL.md` and `references/*.md`, generated.
- `public-docs/scripts/` generator, a shared `sfClientVersion()` module used by `vite.config.ts` and the generator, and the `build:skill` script in `public-docs/package.json`.
- `public-docs/agent-skill/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` at the repository root.
- `public-docs/src/pages/sf-client/AgentSkillPage.vue`, its route, its nav entry, and a row in `public-docs/CLAUDE.md`.
- `dist/<route>.md`, `dist/llms.txt` and `dist/llms-full.txt`, written by the build.
- A CI drift check in `.github/workflows/`.
- A one-line fix in `public-docs/README.md`.
- `docs/diagrams/` source, SVG and PNG for "From docs to agent".
- The exact file list is fixed in `docs/plan/` before implementation.

## Test plan

- `npm run build:skill` is idempotent: a second run changes no file.
- The generator renders all 43 docs pages (the 44th route is the not-found catch-all) without error.
- The drift check fails when a page changes and the skill is not regenerated, and when a name in the references is missing from the SDK's `__all__`.
- `claude plugin validate` passes on the repository root and on the plugin folder.
- `npx skills add <repo> --skill screamingface` installs the skill.
- The new page: review report (three passes, scorecard, trust check) recorded in this ledger.
- Gates in `public-docs`: `npm run type-check`, `npm run lint`, `npm run build`, `npx prettier --check src`.

## Acceptance

- See `docs/spec/2026-11-12-agent-skill-and-md-endpoints.md`.

## Review report (new page `/sf-client/agent-skill`)

Reader: a technical developer (priority 1) whose coding agent should know ScreamingFace. Goal: install the skill with one prompt. Time budget: unavailable (no source supplies it). Operational metrics: unavailable.

### 1. Verdict

A developer reaches a working install command in the first screen: the intro names the skill, the next section is the prompt to paste. Understanding flows through the three install tabs. It breaks at "from the repository" in the manual tab, which named no repository (fixed).

### 2. Friction log

| # | Location | Sentence | Status |
|---|---|---|---|
| 1 | Install the skill, Manual copy | "Copy the folder `public-docs/agent-skill/skills/screamingface` from the repository" | fixed: links the ScreamingFace repository |
| 2 | Install the skill, Claude Code | "installs the plugin `docs` from it, which holds the skill `screamingface`" | open: the plugin and the skill have two names (spec D2) |

### 3. Flow map

The prompt comes before the tabs that explain its commands. The prompt is self-contained, so no reader needs the tabs first.

### 4. Scorecard

| # | Item | Score | Quoted evidence |
|---|---|---|---|
| 1 | First contact | 4 | "The ScreamingFace skill gives a coding agent the ScreamingFace Client docs" |
| 2 | Time to first success | 4 | "Paste this prompt into your coding agent:" |
| 3 | Concept ordering | 4 | "Copy to your agent" comes before "Install the skill" |
| 4 | Learning-curve shape | 4 | three tabs, one command each |
| 5 | Example quality | 3 | `npx skills add ScreamingFace/screamingface --skill screamingface`: installed from a local path, not from GitHub |
| 6 | Reference navigability | 4 | the sidebar entry "Install the agent skill" under How-to guides |
| 7 | Terminology discipline | 3 | plugin `docs` and skill `screamingface` |
| 8 | Honest operations | 4 | "Claude Code applies the update after a restart." |
| 9 | Visual clarity | 4 | the "From docs to agent" diagram, labels equal to the prose |

### 5. Diagram plan

One diagram, "From docs to agent", delivered: `docs/diagrams/agent-skill-docs-to-agent-{light,dark}.{svg,png}`. No further diagram needed.

### 6. Top fixes

| Priority | Location | Before | After | Status |
|---|---|---|---|---|
| 1 | Manual copy tab | "from the repository" | "from the ScreamingFace repository", linked | applied |
| 2 | Install the skill | plugin `docs`, skill `screamingface` | one name | open, spec D2 |

### 7. What already works

The prompt block with a copy button, the troubleshooting table (symptom, cause, fix), and the diagram.

### Trust check

| Check | Result |
|---|---|
| Plain limits | pass: the page states that a plain `npx skills add` lists other skills and that Claude Code needs a restart |
| Numbers over adjectives | pass: no adjective for performance |
| Operational reality | the page states that every page is served as Markdown; this holds after the first deploy (`check-deployed.sh`) |
| Marketing residue | none |
| Versioning | the page names the docs version and how to compare it with the installed package |

## Outcome

- **Actual files:** `public-docs/scripts/` (`sf-version.mjs`, `sf-version.d.mts`, `ssr-entry.ts`, `build-skill.mjs`, `check-skill-names.mjs`, `check-deployed.sh`), `public-docs/src/router/routes.ts` (extracted from `index.ts`), `public-docs/vite.config.ts`, `public-docs/package.json` and `package-lock.json` (`turndown`, `turndown-plugin-gfm`), `public-docs/agent-skill/` (`SKILL.template.md`, generated `SKILL.md`, 44 references, `.claude-plugin/plugin.json`), `.claude-plugin/marketplace.json`, `.github/workflows/public-docs-tests.yml`, `public-docs/src/pages/sf-client/AgentSkillPage.vue`, `public-docs/src/navigation/sf-client.ts`, `public-docs/CLAUDE.md`, `public-docs/README.md`, `docs/diagrams/agent-skill-*` and `render_png.sh`, `public-docs/public/diagrams/agent-skill-*`, and the spec, plan, ledger and mirror.
- **Commits:** `1b023c86b` spec, ledger and mirror; `e210f9d05` spec and plan approved; `0222a8276` generator, `.md` endpoints and `llms.txt`; `b6269fcd6` skill, install files and drift check; `fcffb211c` docs page, diagram and README fix; and the commit that fills this Outcome.
- **Gates:** `npm run type-check`, `npx oxlint .`, `npx eslint .` and `npm run build` pass in `public-docs`. `npx prettier --check` passes on `scripts`, `src/router` and `AgentSkillPage.vue`. `npm run build:skill` and `npm run build` are idempotent. `node scripts/check-skill-names.mjs` passes against release 0.1.12 (104 public names). `claude plugin validate` passes on the repository root and on `public-docs/agent-skill`. `npx skills add <repo> --skill screamingface -a claude-code` installs the skill into a clean project.
- **Deviations:** (1) No probe file: `check-deployed.sh` replaces it (spec D15). (2) No `CopyBlock` component: the existing `CodeBlock` has the copy button. (3) The nav entry is in "How-to guides", not "Get started". (4) `build:skill` is in commit 1 and writes only references until commit 2. (5) The Caddy `basicauth` example and the "Remaining for go-live" section of `public-docs/README.md` are unchanged. (6) `npx prettier --check src` fails on 11 page files on `main` that this unit did not change.
- **Not verified:** the install from the GitHub source (`claude plugin marketplace add ScreamingFace/screamingface` and `npx skills add ScreamingFace/screamingface`), because the branch is not on the default branch; the `Content-Type` of a deployed `.md` file, until `check-deployed.sh` runs after the first deploy.
- **Review report:** in this ledger, for the new page.
