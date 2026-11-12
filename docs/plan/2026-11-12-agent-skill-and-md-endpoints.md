# Agent skill and plain-text docs endpoints: plan

Status: approved · Refs: `OME-1894` · Spec: `docs/spec/2026-11-12-agent-skill-and-md-endpoints.md` (approved)
Branch: `callis/ome-1894-experience-using-sf-with-claude-code-codex`, from `origin/main` at `2d9c18632`.
Landing: `public-docs`, `.claude-plugin/`, `.github/workflows`, `docs/diagrams`, `docs/spec`, `docs/plan`, `docs/work`, `docs/tasks`.

## 1. Shape of the delivery

One pull request with three commits. Each commit is approved before it is made, and push is approved separately. No Linear issue is created: `OME-1894` exists.

| Commit | Scope | Spec decisions |
|---|---|---|
| 1 | Generator, shared version module, `llms.txt`, `llms-full.txt`, `.md` endpoints | D5, D6, D7, D8, D9, D15 |
| 2 | `SKILL.md` and references, `plugin.json`, `marketplace.json`, drift check | D1, D2, D3, D4, D10, D11, D13, D14 |
| 3 | Docs page, copy block, route, nav entry, diagram, README fix, review report | D12, D16, D17, D18, D19 |

## 2. Commit 1: generator and endpoints

Files:

- `public-docs/scripts/sf-version.mjs` exports `sfClientVersion()`: the `git describe --tags --match 'screamingface-v[0-9]*' --exclude '*rc*' --abbrev=0 HEAD` call and the `screamingface-v` strip, moved from `vite.config.ts` unchanged. `public-docs/scripts/sf-version.d.mts` types it.
- `public-docs/vite.config.ts` imports `sfClientVersion()` from that module. Its output is unchanged.
- `public-docs/src/router/routes.ts` holds the `routes` array. `src/router/index.ts` imports it and still creates the router. The generator imports `routes.ts` without creating a browser history.
- `public-docs/scripts/ssr-entry.ts` exports `render(component, path)`: a memory router with a catch-all route, Pinia, `createSSRApp`, `renderToString`.
- `public-docs/scripts/build-skill.mjs`:
  1. Starts a Vite server with `configFile: false`, the `vue()` plugin, the `@` alias and `__SF_CLIENT_VERSION__` defined, so the HTML has no devtools attributes.
  2. Loads `routes.ts` and the navigation modules (`sfClientNavigation`, `sfClientReferenceNavigation`, `learnNavigation`) through `ssrLoadModule`.
  3. Renders every route, extracts the page `header` and the `.prose-content` div, converts them with `turndown` and `turndown-plugin-gfm` with the four rules of D7.
  4. Writes each page as `# <title>`, `Source: https://docs.screamingface.ai<route>`, then the body.
  5. With `--dist`, writes `dist/<route>.md`, `dist/llms.txt` and `dist/llms-full.txt`. Without it, writes `public-docs/agent-skill/skills/screamingface/references/<route with / replaced by ->.md` (commit 2).
  6. Fails with a non-zero exit when a route does not render, a body is empty, a tag remains in the Markdown, or a code fence holds an escaped `\=` or `\[`.
- `public-docs/package.json`: devDependencies `turndown`, `turndown-plugin-gfm`; scripts `build:skill` (`node scripts/build-skill.mjs`) and `postbuild` (`node scripts/build-skill.mjs --dist`). `npm run build` is otherwise unchanged and the deploy workflow needs no change.
- `public-docs/scripts/check-deployed.sh`: the post-deploy check of D15. It needs `curl` only.
- `public-docs/CLAUDE.md`: the Development Commands list names `build:skill`.

Verification: all 44 routes render; a second `npm run build:skill` changes no file; `dist` holds one `.md` per route and both `llms` files; `sfClientVersion()` returns the same value in `vite.config.ts` and in the generator; `npm run type-check`, `lint`, `build` and `prettier --check` pass.

## 3. Commit 2: skill, install files, drift check

Files:

- `public-docs/agent-skill/SKILL.template.md`: the fixed preamble. It holds only statements that a docs page holds: what the package is, the Python version, the chain syntax, hosted login with `Client.login()`, the local engine limits, and a task-to-reference table. No performance adjective, no claim outside the product-context claims table.
- `public-docs/agent-skill/skills/screamingface/SKILL.md`: frontmatter (`name: screamingface`, `description`), the template, the version, and the generated index of references grouped by nav. Generated.
- `public-docs/agent-skill/skills/screamingface/references/*.md`: generated, one per route.
- `public-docs/agent-skill/.claude-plugin/plugin.json`: `name: docs`, description, author, and the version written by the generator. Generated.
- `.claude-plugin/marketplace.json`: `name: screamingface`, owner, one plugin `docs` with `source: ./public-docs/agent-skill`. Static.
- `public-docs/scripts/check-skill-names.mjs`: reads every `sf.<Name>` in the references, installs the release that `sfClientVersion()` names in a temporary environment, reads its `__all__`, and fails when a referenced name is missing from `__all__` or a name in `__all__` is referenced nowhere.
- `.github/workflows/public-docs-tests.yml`: new steps in the existing job: `npm run build:skill`, `git diff --exit-code -- public-docs/agent-skill`, `actions/setup-python` (Python 3.12), then the names check, which creates a venv and installs the release with `pip`. The job already checks out full history for the version tag and sets up Node from `.nvmrc`.

Verification: `claude plugin validate` passes on the repository root and on `public-docs/agent-skill`; `npx skills add <local repo> --skill screamingface` installs into a clean project; the drift step fails when a page changes without regeneration (tested once by hand); the names check fails on a planted wrong name (tested once by hand).

## 4. Commit 3: docs page

Files:

- `public-docs/src/components/ui/CopyBlock.vue`: a code block with a copy button, using the existing `useCopy` composable.
- `public-docs/src/pages/sf-client/AgentSkillPage.vue`: a how-to page with three tabs (`Tabs`): Claude Code, other agents, manual copy; the copy prompt of the spec; update commands (`claude plugin marketplace update screamingface`, `claude plugin update docs@screamingface`, `npx skills update`); troubleshooting (the agent does not use the skill, a plain `npx skills add` lists only internal skills, a stale skill).
- `public-docs/src/router/routes.ts`: route `/sf-client/agent-skill`, name `sf-client-agent-skill`.
- `public-docs/src/navigation/sf-client.ts`: entry in the "Get started" group after Installation.
- `public-docs/CLAUDE.md`: a route row and `CopyBlock` in the component list.
- `docs/diagrams/agent-skill-diagrams.gen.py`, with SVG and PNG in `docs/diagrams/` and the SVG pair in `public-docs/public/diagrams/`: "From docs to agent". `render_png.sh` is reused.
- `public-docs/README.md`: the sentence about a temporary password gate is removed.
- `docs/work/2026-11-12-agent-skill-and-md-endpoints.md`: the review report (three passes, scorecard with a quoted line for each of the nine items, trust check) and the Outcome.
- The generated files are regenerated, because the new page is a route: references, `llms.txt`, `llms-full.txt`.

Verification: the page renders locally with the copy button and the three tabs; the page text has no dash and no title-case heading; the copy prompt on the page equals the spec's; the drift check passes after regeneration; the gates pass.

## 5. After the merge and deploy

1. `public-docs/scripts/check-deployed.sh`: it exits 0 when `/favicon.svg`, `/llms.txt`, `/llms-full.txt` and two `.md` endpoints answer `200` with the expected `Content-Type`. A `200 text/html` means the file is missing.
2. `curl https://docs.screamingface.ai/llms.txt`: it lists every `.md` link.
3. `claude plugin marketplace add ScreamingFace/screamingface`, then `claude plugin install docs@screamingface`, in a clean Claude Code profile.
4. `npx skills add ScreamingFace/screamingface --skill screamingface` in a clean project.
5. If the `.md` type is wrong, a follow-up PR adds a Caddy header rule through the VM owner.
6. Fill the ledger Outcome and close the Linear issue.

## 6. Global constraints

- A statement in the skill or the page is true on the docs version, or is removed.
- No em-dash or en-dash and no narrative in any added file.
- The generated files are never edited by hand.
- Product-context casing: ScreamingFace Client and Engine are capitalised, `url4` is lower case.
- The PR body follows `.github/pull_request_template.md` with `**Refs:** OME-1894` and no attribution line.

## 7. Decisions (confirmed, with the checks that validated them)

- **D15:** no probe file. `check-deployed.sh` replaces it. Tested against the site before this change: it passes for `/favicon.svg` and fails for the other four URLs.
- **Generator language:** plain `.mjs` with a `.d.mts` for the shared version. In a scratch copy, `sfClientVersion()` returns `0.1.12`, equal to `git describe`; `vue-tsc --noEmit`, `vite build` and `oxlint` pass.
- **Routes module:** `routes.ts` extracted from `router/index.ts`. In a scratch copy the 44 `(path, name, component)` triples are identical and in order; type-check and build pass.
- **CI placement:** extend `public-docs-tests.yml`. The job has `fetch-depth: 0` and `setup-node`; it gets `setup-python`. `pip install screamingface==0.1.12` in a venv gives 105 names.

## 8. Risks

- `scripts/ssr-entry.ts` and the generator are not covered by `type-check`, which covers `src/**` and the config files. ESLint covers `.ts` and `.mts` files, so `ssr-entry.ts` is covered by ESLint and oxlint, and the `.mjs` files by oxlint only.
- A page that uses a browser-only API would fail the render. All 44 routes rendered in the spike, and the generator fails the build on a new failure.
- The names check needs network access to install a release in CI.
- The committed references change with every docs change and every release.
