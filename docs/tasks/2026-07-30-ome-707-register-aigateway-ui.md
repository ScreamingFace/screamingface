---
id: OME-707
linear_url: https://linear.app/openmined/issue/OME-707/register-aigateway-ui-ci-lane-release-lane-codeowners-dependabot-sdlc
status: in_progress
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-07-30
closed:
ledger: docs/work/2026-07-30-OME-707-register-aigateway-ui.md
---

# OME-707 — Register aigateway-ui: CI lane, release lane, CODEOWNERS, dependabot, sdlc card

The repo-plumbing half of `OME-705`. Makes `apps/aigateway-ui` a first-class component per the
6-step new-component checklist in the `working-in-this-repo` skill. **No dependency on `OME-684`**
— can start immediately.

`aigateway-ui` is the repo's **first non-Python stack**, so several single-stack assumptions
surface here.

| File | Change |
|---|---|
| `.github/workflows/aigateway-ui-tests.yml` | New, path-filtered. `setup-node@v4` + `cache: npm`. `npm ci` → `npm run lint` → `npx tsc --noEmit` → `vitest --coverage`. Keep `dorny/test-reporter@v2`, `orgoro/coverage@v3.2`, the `cost` job |
| `release-please-config.json` + `.release-please-manifest.json` | `component: aigateway-ui`, `tag-separator: "-"`, `include-component-in-tag: true`. Root `release-type` is already `node` |
| `.github/workflows/release-aigateway-ui.yml` | Copy `release-aigateway.yml`; tag `aigateway-ui-v*`; verify reads `package.json` not `pyproject.toml` |
| `.github/CODEOWNERS` | `/apps/aigateway-ui/` matching `/apps/aigateway/`'s owner |
| `.github/dependabot.yml` | First `npm` ecosystem in the repo |
| `.claude/sdlc.local.md` | Fifth stack: `root: apps/aigateway-ui`, `skill: sdlc-react`, npm `gates:`. `run_gates.py` is stack-agnostic — no script change |
| `.githooks/pre-push` | `run_stack apps/aigateway-ui aigateway-ui` |
| `CONTRIBUTING.md` | Node prerequisite row, stacks-table row, run-from-source block, releases row |
| `.claude/skills/working-in-this-repo/SKILL.md` | Routing-table row |

## Watch out

**Do not** add `sdlc-react` to `check_loop_parity.py` — it hardcodes
`["sdlc-python", "sdlc-electron"]`, and adding it imposes a byte-identical `SHARED-LOOP` region
constraint gated by `repo-checks.yml`. Reference the global plugin skill instead of vendoring one.

Port **9107** — 9105 aigateway, 9106 scoreboard, 9108 url4-cloud are taken.

## Acceptance

A trivial PR touching only `apps/aigateway-ui/**` triggers `aigateway-ui-tests.yml` and nothing
else; `uv run .claude/scripts/run_gates.py aigateway-ui` runs the npm gates locally.
