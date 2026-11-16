---
ticket: OME-1894
stack: repo
status: done
started: 2026-11-12
finished: 2026-11-16
---

# agent-skill-and-md-endpoints: Experience using SF with Claude Code / Codex is good

## Intent

Publish a `screamingface` agent skill and plain-text docs endpoints, both generated from the ScreamingFace Client docs, so a coding agent installs the skill with one prompt and reads any docs page as Markdown.

## Planned changes

- `public-docs/agent-skill/skills/screamingface/SKILL.md`, generated: preamble and an index of links to the docs pages and their `h2` and `h3` headings. No `references/` folder (spec D3, D9).
- `public-docs/scripts/` generator, a shared `sfClientVersion()` module used by `vite.config.ts` and the generator, and the `build:skill` script in `public-docs/package.json`.
- `public-docs/agent-skill/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` at the repository root.
- `public-docs/src/pages/sf-client/AgentSkillPage.vue`, its route, its nav entry, and a row in `public-docs/CLAUDE.md`.
- `dist/<route>.md`, `dist/llms.txt` and `dist/llms-full.txt`, written by the build.
- A CI drift check in `.github/workflows/`.
- A one-line fix in `public-docs/README.md`.
- `public-docs/src/components/layout/DocLayout.vue`: the copy-link button on section headings (D20). `public-docs/src/lib/slug.ts`: the shared heading slug (D21).
- `public-docs/src` formatted with Prettier (D22).
- `docs/diagrams/` source, SVG and PNG for "From docs to agent".
- The exact file list is fixed in `docs/plan/` before implementation.

## Test plan

- `npm run build:skill` is idempotent: a second run changes no file.
- Every heading link in the index points at an id that `DocLayout` assigns, checked in a browser for all pages. The copy-link button copies the page address with `#<id>`, checked in a browser. Formatting leaves every `dist/**/*.md` equal.
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

- **Actual files:** `public-docs/scripts/` (`sf-version.mjs`, `sf-version.d.mts`, `ssr-entry.ts`, `build-skill.mjs`, `check-skill-names.mjs`, `check-deployed.sh`), `public-docs/src/router/routes.ts` (extracted from `index.ts`), `public-docs/src/lib/slug.ts`, `public-docs/src/components/layout/DocLayout.vue`, `public-docs/vite.config.ts`, `public-docs/package.json` and `package-lock.json` (`turndown`, `turndown-plugin-gfm`), `public-docs/agent-skill/` (`SKILL.template.md`, generated `SKILL.md`, `.claude-plugin/plugin.json`), `.claude-plugin/marketplace.json`, `.github/workflows/public-docs-tests.yml`, `public-docs/src/pages/sf-client/AgentSkillPage.vue`, `public-docs/src/navigation/sf-client.ts`, `public-docs/CLAUDE.md`, `public-docs/README.md`, `docs/diagrams/agent-skill-*` and `render_png.sh`, `public-docs/public/diagrams/agent-skill-*`, 12 page files formatted with Prettier, and the spec, plan, ledger and mirror.
- **Commits:** `1b023c86b` spec, ledger and mirror; `e210f9d05` spec and plan approved; `0222a8276` generator, `.md` endpoints and `llms.txt`; `b6269fcd6` skill, install files and drift check; `fcffb211c` docs page, diagram and README fix; `86466d110` ledger outcome; `aa75095d9` merge of `origin/main`; `50284e41a` roadmap kept out of the skill; `1bc023261` entity decoding and comment stripping in the generator; `c9a72c725` spec and plan amendment; `1ea77caa2` copy-link button; `971143416` shared heading slug; `6e9497176` index in place of the references; `2c5af9990` Prettier; `d70e0080b` ledger outcome; `7e61648bf` tag removal in a loop in the generator (CodeQL); `514fa3602` skill rules 6 and 7 (open the docs page before use, end the answer with a `Sources` list).
- **Gates:** `npm run type-check`, `npx oxlint .`, `npx eslint .`, `npm run build` and `npx prettier --check src` pass in `public-docs`. `npm run build:skill` and `npm run build` are idempotent. `node scripts/check-skill-names.mjs` passes against release 0.1.12 (104 public names). `claude plugin validate` passes on the repository root and on `public-docs/agent-skill`. `npx skills add <repo> --skill screamingface -a claude-code` installs `SKILL.md` into a clean project.
- **Index check:** `SKILL.md` links 44 pages and 320 `h2` and `h3` headings, 40,624 bytes. In Edge, the ids of all 328 `h2`, `h3` and `h4` headings on 45 routes are identical before and after the slug move, and the 320 index links equal the `h2` and `h3` ids in order. The hash of every `dist/**/*.md` and `llms*.txt` file is equal before and after formatting.
- **Copy-link button:** in Edge on `/sf-client/api/reducers`, each of the 8 headings has one button; a click copies the page address with `#<id>`; the tip reads "Link copied" for 2 seconds; without clipboard access the hash goes to the address bar; the button takes keyboard focus; an author-set id is kept.
- **Deviations:** (1) No probe file: `check-deployed.sh` replaces it (spec D15). (2) No `CopyBlock` component: the existing `CodeBlock` has the copy button. (3) The nav entry is in "How-to guides", not "Get started". (4) The Caddy `basicauth` example and the "Remaining for go-live" section of `public-docs/README.md` are unchanged. (5) The skill holds an index of links in place of 44 reference files (spec D3, D9), after the review of the first version.
- **Agent tests:** `sf-skill-test/test-first-fusion.md` (outside the repository) holds four runs of one prompt. With only `Skill` and `Read` and the local pages, the agent wrote a `Fanout >> Synthesize` chain whose names are in `__all__` and whose signatures match, and listed the pages it read. With only `Skill` and `WebFetch`, every fetch returned the page title, because the live site serves no `.md` file before the deploy. The code was not executed.
- **Installs from GitHub:** `npx skills add "ScreamingFace/screamingface#<branch>"` and `claude plugin marketplace add "ScreamingFace/screamingface#<branch>"` install the skill with 320 index links.
- **Not verified:** the `Content-Type` of a deployed `.md` file and the live fetch test, until the merge and deploy and `check-deployed.sh`; the hosted login prompt; the execution of an agent's output.
- **Review report:** in this ledger, for the new page.
