# Agent skill and plain-text docs endpoints for the ScreamingFace Client docs

Status: draft · Stack: repo · Issue: `OME-1894` · Parent: `OME-1313`

## Problem

A coding agent that works with ScreamingFace has no installable instructions and no plain-text view of the docs. `public-docs` is a Vue single-page app: every unknown path returns `200 text/html`, including `/llms.txt`, and there is no skill, no marketplace file and no per-page Markdown.

## Context

| Slot | Value |
|---|---|
| Reader | A coding agent (Claude Code, Codex, others), and the technical developer (priority 1) who installs the skill and reads the docs page. |
| Register | Direct and technical. |
| Terminology | Product-context casing: ScreamingFace Client, Engine and Leaderboard are capitalised, `url4` is lower case, "fusion" is the lead noun. |
| Source of truth | The ScreamingFace Client docs pages in `public-docs/src/pages`. The skill is generated from them. |
| Docs version | The newest non-rc `screamingface-v*` tag reachable from HEAD, read by `sfClientVersion()` in `public-docs/vite.config.ts`. |
| Linear | `OME-1894`, labels `repo-dev-processes`, `autonomous`, `agentic`. |
| Site | `https://docs.screamingface.ai`, built by `npm run build`, rsynced to a VM and served by Caddy `file_server` behind Cloudflare. |

## Decisions

| # | Decision |
|---|---|
| D1 | The skill lives in this repository, in `public-docs/agent-skill/`. |
| D2 | The skill is named `screamingface`. The plugin is named `docs` and the marketplace is named `screamingface`, so the Claude Code install id is `docs@screamingface`. The plugin name is the same in `marketplace.json` and in `plugin.json`. |
| D3 | The skill's reference files are generated from the docs pages. No reference file is edited by hand. |
| D4 | `SKILL.md` is the frontmatter (`name`, `description`), a fixed preamble from `public-docs/agent-skill/SKILL.template.md`, and a generated index of the reference files. The preamble holds only statements that the docs pages hold. |
| D5 | The skill version is the docs version: one shared `sfClientVersion()` module, imported by `vite.config.ts` and by the generator. There is one copy of the `git describe` command. |
| D6 | The generator renders each route with Vite SSR and `@vue/server-renderer` through a memory router, extracts the page `header` and the `.prose-content` div, and converts them with `turndown` and its GFM plugin. |
| D7 | The generator applies four rules: take code from any `<pre>`; put the language label into the code fence; drop the `In [n]` labels of `NbCell`; replace each diagram with its alt text. |
| D8 | The build writes `dist/<route>.md` for each route, `dist/llms.txt` (an index grouped by the nav tree, each entry with its description and its `.md` link) and `dist/llms-full.txt` (every page in nav order). |
| D9 | A reference file is `references/<route with / replaced by ->.md`, for example `sf-client-api-reducers.md`. Each starts with `# <title>`, then `Source: https://docs.screamingface.ai<route>`. |
| D10 | The Claude Code install is `.claude-plugin/marketplace.json` at the repository root, with one plugin named `docs` whose `source` is `./public-docs/agent-skill`, and `public-docs/agent-skill/.claude-plugin/plugin.json`. |
| D11 | The other agents' install is `npx skills add ScreamingFace/screamingface --skill screamingface`. The page and the copy prompt always include `--skill screamingface`. |
| D12 | The docs page is `/sf-client/agent-skill`, in the "Get started" nav group. It has three tabs (Claude Code, other agents, manual copy), a "Copy to your agent" prompt block with a copy button, update commands and troubleshooting. |
| D13 | The generated skill is committed, because the marketplace installs from git. A CI step regenerates it and fails when the committed copy differs. |
| D14 | The drift check fails when a `sf.<Name>` in the references is missing from `screamingface.__all__` of the release that the docs version names, and when a name in that `__all__` appears in no reference. |
| D15 | One probe file ships with the build so that the `Content-Type` of a deployed `.md` is read after the first deploy. |
| D16 | A line in `public-docs/README.md` that says the site is behind a temporary password gate is removed. |
| D17 | The preamble of `SKILL.md` and the docs page follow the product-context terminology and claims table, and the writing-docs prose rules: one Divio page type (the page is a how-to), no narrative, no em-dashes or en-dashes, sentence-case headings, numbers instead of adjectives. |
| D18 | The docs page carries one diagram, "From docs to agent": the docs pages, the generator, the committed skill and the `.md` endpoints, and the two install routes. Source in `docs/diagrams/`, light and dark SVG and PNG, labels equal to the prose. |
| D19 | The new page is reviewed with the writing-docs procedure (three passes, nine-item scorecard, trust check). The report is recorded in the work ledger. |

## Copy prompt

```
Install the ScreamingFace skill for this project.
In Claude Code, run:
  claude plugin marketplace add ScreamingFace/screamingface
  claude plugin install docs@screamingface
In other agents, run:
  npx skills add ScreamingFace/screamingface --skill screamingface
Use one installation method. Then use the screamingface skill when writing code with the screamingface Python package.
```

## Deliverables

1. `public-docs/agent-skill/skills/screamingface/SKILL.md`.
2. `public-docs/agent-skill/skills/screamingface/references/*.md`, one per docs route.
3. `npm run build:skill` in `public-docs`, with the shared `sfClientVersion()` module.
4. `.claude-plugin/marketplace.json` and `public-docs/agent-skill/.claude-plugin/plugin.json`.
5. `dist/<route>.md`, `dist/llms.txt`, `dist/llms-full.txt` and the probe file.
6. The docs page, its route, its nav entry and a row in `public-docs/CLAUDE.md`.
7. The CI drift check.
8. The README fix.
9. The diagram "From docs to agent".
10. The review report of the new page, in the work ledger.

## Spike results (measured 2026-11-12)

- `npx skills add <repo> --skill screamingface -a claude-code` installs a skill at `public-docs/agent-skill/skills/screamingface/SKILL.md` to `./.claude/skills/screamingface`. A plain `--list` on a repository that has `.claude/skills` shows only those skills; `--full-depth` shows both. This repository has nine skills in `.claude/skills`. Tested with a local path source.
- `claude plugin validate` passes on a root `.claude-plugin/marketplace.json` with `"source": "./public-docs/agent-skill"` and on the plugin folder. The only warning is a missing author. `marketplace add` was not run.
- All 44 routes render through Vite SSR and `@vue/server-renderer` with no error and no Vue warning. The Markdown output for all pages is 354,366 characters, the largest page 23,688.
- Every unknown path on `docs.screamingface.ai` returns `200 text/html`. A static `.svg` returns `image/svg+xml`. The `Content-Type` of a `.md` file is not known.
- Nothing in the repository reads `.claude-plugin/`, and `.gitignore` does not ignore it. `CODEOWNERS` routes a root file to `@sergio-bershadsky` and `@HupBaHa`, and `/public-docs/` to `@IrinaMBejan`.

## Out of scope

- Plugin hooks, slash commands or an MCP server.
- Cursor or other agent rule files.
- Submitting to Anthropic's or skills.sh's directories.
- Translating pages.
- Changing page content, except where the generator finds a page that cannot be rendered.

## Risks

- The references total 354,366 characters over 44 pages. An agent may skip or truncate a long reference. `SKILL.md` stays short and its index names one reference file per task. Whether an agent skips a reference is not measured.
- A root `.claude-plugin/marketplace.json` is reviewed by the root code owners, `@sergio-bershadsky` and `@HupBaHa`, not by the docs owner.
- The committed copy produces a skill diff for every docs change and for every release. The drift check keeps it equal to the docs.
- The `Content-Type` of a deployed `.md` is unknown until the first deploy. A missing `.md` returns `200 text/html`, so the check reads the header and not the status.
- The install from a GitHub source (not a local path) is untested until the branch is pushed.

## Verification

- `npm run build:skill` run twice leaves no diff.
- The drift check fails on a changed page and on a name missing from `__all__`.
- `claude plugin validate` passes on the repository root and on the plugin folder.
- `npx skills add <repo> --skill screamingface` installs the skill into a clean project.
- An agent with only the skill writes a correct `sf.Fanout(...) >> sf.Synthesize(...)` chain and a correct hosted login, checked by running its output.
- Every route has a `.md` endpoint in `dist`, and `llms.txt` lists them all.
- After the first deploy: `curl -I` on the probe file shows its `Content-Type`.
- `npm run type-check`, `npm run lint`, `npm run build` and `npx prettier --check src` pass in `public-docs`.

## Acceptance

- Every deliverable above exists.
- The skill version equals the footer's release label.
- The drift check is green on a clean checkout.
- The docs page shows the exact copy prompt above.
- The diagram exists as source, SVG and PNG and is placed on the page.
- The review report exists in the ledger, with a quoted line for each of the nine scores.
- No page or artifact of this unit contains an em-dash or an en-dash, and no heading is in title case.
- One pull request with three commits: the generator and endpoints; the skill, the install files and the drift check; the docs page, the nav entry and the README fix.
