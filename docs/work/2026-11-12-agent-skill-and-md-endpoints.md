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

## Outcome (fill at the end, required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
