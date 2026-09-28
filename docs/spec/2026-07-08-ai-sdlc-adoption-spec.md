---
title: AI SDLC adoption — Linear work items, repo docs artifacts, per-stack skills
status: approved-design, pending-implementation
created: 2026-07-08
author: Sergey Bershadsky + Claude (Fable 5)
supersedes: Asana-based git workflow in CLAUDE.md (SF-N tickets)
related:
  - .docs/teardown-plan.md (SF-348, PR #371)
  - docs/diagrams/work-item-topology.png (+ .svg source)
  - https://linear.app/openmined/project/screamingface-v1-27666092fc7f (default Linear project)
  - https://github.com/sergio-bershadsky/ai/tree/main/plugins (source of sdlc/task-management artifacts)
---

# AI SDLC adoption — spec

## Context

After the SF-348 re-foundation, the repo hosts `apps/aigateway`, `apps/scoreboard`, and a
reserved `packages/` root, with new desktop/CLI packages incoming. Development process moves
from Asana-centric SF-N tickets to a repo-local AI SDLC: **Linear** as the dev work-item
system of record, mandatory in-repo artifacts (`docs/tasks`, `docs/work`, `docs/spec`,
`docs/plan`, `docs/diagrams`), and rigid per-stack SDLC skills adapted from the external
sdlc plugin (sergio-bershadsky/ai). Pasted plugin artifacts are adapted critically, not
copied verbatim.

## Decisions locked (2026-07-08)

| # | Decision | Choice |
|---|---|---|
| D1 | System of record | **Linear** is the single system of record for dev work items; the task-management skill runs on it. |
| D2 | Ticket IDs *(revised twice same day)* | **The existing `openmined` workspace Engineering team, key `OME`** — one global sequence `OME-N` for every work item (the Asana SF-N model). No new team is created in the shared org workspace. Per-component team keys (`AAGW-321` style) and a dedicated `OM` team were evaluated and dropped. No zero-padding (Linear cannot render it — verified; sources below). |
| D3 | Asana role | **Strictly read-only** source of product/marketing top-level tasks (list/read/search). Never create or update. Technical work items NEVER go to Asana. |
| D4 | Linear access *(revised twice)* | **The Linear MCP plugin, activated/authenticated in Claude, is the ONLY transport and a hard PRECONDITION** (`/mcp` → plugin:linear connected). **API tokens / raw GraphQL are FORBIDDEN.** Operations the MCP cannot perform (label deletion, team creation, workflow states) are OWNER actions in the Linear UI. |
| D5 | Stack skills now *(revised)* | `sdlc-python` + **`sdlc-electron`** (transformed from the source plugin's sdlc-react for the upcoming desktop app: main/preload/renderer idiom, both-side IPC contract rule S2, security posture — contextIsolation on, external HTTP in main only). **`sdlc-go` deferred** until a Go component exists (YAGNI). |
| D6 | Docs dirs | `docs/tasks/`, `docs/work/`, `docs/spec/`, `docs/plan/`, `docs/diagrams/` (spec/plan singular — user decision). |
| D7 | Repo/process work | Plain **`repo`** label, no `app/*`/`pkg/*` label. |
| D8 | Ledger timing | Ledger file created at work **start** (`docs/work/YYYY-MM-DD-<ticket-id>-<desc>.md`, date = start), frontmatter `status: planned|in_progress|done` + `finished:` date at close. Reconciles "ledger-first" (sdlc rule 1) with "write ledger when finished" (user rule 2). |
| D9 | Cross-cutting work | Work spanning ≥2 apps/packages is **signed as a cross-app product component via labels**: `com/<component>` + every affected `app/*`/`pkg/*` label, filed as an **epic with one sub-issue per affected app/package**. |
| D10 | Label taxonomy — **LOCKED (align + extend)** | The existing Engineering **`Epic` label group children remain the workstream/component axis** (one per issue: url4 Engine, AI Gateway, Eval Runner & Datasets, Results & Runs, Leaderboard, Auth & Subsidized Compute, Desktop App, Python SDK, Multi-turn Ensembles, SOTA Hunt, Compute Budgeting). **Added:** `actor` group (D13), `who-acts` group (design-session/autonomous/deferred), plain landing labels `app/aigateway`, `app/scoreboard`, `pkg/url4-python-sdk`, `repo`, and `needs-owner`. **Reused:** existing `blocked ⛔`. **No `com/*` axis, no `type` group** (plain `Bug`/`Feature`/`Improvement` reused where useful; epics are parent issues). Obsolete trial labels (`com/*`, `type` group, plain `blocked`) → owner deletes in UI. |
| D13 | Actor label — **MANDATORY, LOCKED** | Every work item carries exactly one **`actor` group label: `agentic` or `human`** — who executes it. Set at filing; flipped if ownership changes. |
| D11 | Default project | Every work item for this repo attaches to the Linear project **😱 ScreamingFace V1** (`screamingface-v1-27666092fc7f`). |
| D12 | STOP signals | The Engineering team's workflow is SHARED — we do not add states to it. `Blocked` / `Needs Owner` are **workspace labels** (`blocked`, `needs-owner`): a STOP = apply the label + a comment stating the exact question; the issue stays In Progress. Clearing the STOP removes the label. |

Linear research sources: [conceptual model](https://linear.app/docs/conceptual-model),
[Teams](https://linear.app/docs/teams), [Creating issues](https://linear.app/docs/creating-issues),
[Editor](https://linear.app/docs/editor), [Collapsible sections changelog](https://linear.app/changelog/2025-03-19-collapsible-sections).

## 1. Work-item topology

**We are ONE team.** Work items live in the existing **Engineering** team (key **`OME`**,
id `5f4d721f-4452-4ed1-990a-7cdbcd923508`) → every work item is `OME-N`, one global
sequence — attached to the **😱 ScreamingFace V1** project (D11). WHERE the work lands and
WHAT it affects live in **labels**, not in the ID:

| Axis | Labels | Notes |
|---|---|---|
| Workstream/component — ONE per issue | existing **`Epic` group** children: url4 Engine, AI Gateway, Eval Runner & Datasets, Results & Runs, Leaderboard, Auth & Subsidized Compute, Desktop App, Python SDK, Multi-turn Ensembles, SOTA Hunt, Compute Budgeting | pre-existing team layout, adopted as-is (D10) |
| Repo landing (WHERE) — multi-value | plain `app/aigateway`, `app/scoreboard`, `pkg/url4-python-sdk`; `app/desktop`, `app/cli` at name lock | added by us |
| Repo/process work | plain `repo` (no app/pkg label) | added by us (D7) |
| `who-acts` group — ONE per issue | `design-session`, `autonomous`, `deferred` | added by us |
| `actor` group — ONE per issue, MANDATORY (D13) | `agentic`, `human` | added by us |
| STOP labels (D12) | existing `blocked ⛔` + added `needs-owner` | label + comment, not states |

Mechanics:
- `app/*`/`pkg/*` are **plain labels** — an issue may carry several (required for
  cross-cutting epics). `who-acts` and `actor` are **Linear label groups**, so Linear
  itself enforces one-per-issue. The workstream axis is the existing `Epic` group.
- New app/package/workstream ⇒ its label registered in the card **in the same change**
  that introduces it (workstream additions coordinated with the project lead).
- Priority: Linear's native field (card maps P1→High(2), P2→Medium(3), P3→Low(4); Urgent(1)
  reserved for incidents).
- Workflow states: the Engineering team's EXISTING set (`Todo → In Progress → In Review →
  Done`, plus its backlog/triage states). We add none (D12); STOPs are labels + comment.
- Epics = Linear parent issues with sub-issues; milestones = milestones of the
  ScreamingFace V1 project.

**Cross-cutting rule (D9):** ≥2 `app/*`/`pkg/*` labels ⇒ the work is cross-cutting: file an
**epic** carrying its workstream (`Epic` group) label + all affected `app/*`/`pkg/*` labels,
with **one sub-issue per affected app/package** (one SDLC unit each; each sub-issue carries
its own `app/*`/`pkg/*` label + the same workstream label). Never one mega-ticket, never
filed as if it were single-app work.

**Registry card:** `.claude/task-board.local.md` — **committed** (repo config, not personal).
Contains: workspace slug, team key+ID, default project (name/slug/ID), state name→ID map
(existing states), label registry (all namespaces + group IDs + STOP labels), priority map,
close-comment template, transport note (MCP ONLY — tokens/GraphQL forbidden). Label
registry sections: `epic_group:` (workstream children), `landing:` (app/pkg/repo),
`who_acts:`, `actor:`, `stop:`. Card missing → HARD STOP (same rule as the source skill).

## 2. Skills (repo-local, `.claude/skills/`)

### 2.1 `asana-product` (transform of the global asana skill)
- Operations kept: list projects/tasks, read task, search, parse URLs.
- Operations REMOVED: create, update, complete, move, sections-add.
- Hard rules in skill text: Asana is a read-only source of product/marketing top-level tasks
  defined by product/marketing tooling; NEVER create any ticket in Asana; NEVER mirror
  technical work there. A dev work item descending from a product task carries the Asana URL
  in its Linear description (`asana_url` in the docs/tasks mirror frontmatter).

### 2.2 `task-management` (Linear rewrite of the source skill)
Keeps verbatim-in-spirit: announce line, card-resolution HARD STOP, single-task-holder rule,
lifecycle (PLAN → TICKETS → owner ticket review → plan one ticket → implement via stack SDLC
→ close → next), batching, mid-session-discovery rule (file first, 30 seconds), close
discipline (commits + gates + ledger paths + deviations in a comment before Done),
anti-pattern table (label-discipline rows: cross-cutting with a single app label → D9 STOP;
minting unregistered labels → register in card first).
Changes:
- **Transport: the Linear MCP tools ONLY** (`save_issue`, `save_comment`, `list_issues`,
  `create_issue_label`, …) — activated in Claude as a precondition (D4). Tokens/GraphQL
  are forbidden; MCP-uncovered operations go to the owner (Linear UI).
- Every work item sets `project: 😱 ScreamingFace V1` (D11) and `team: Engineering`.
- No retitle/code bookkeeping — Linear assigns `OME-N` natively.
- Affect matrix: **entirely labels** — `app/*`/`pkg/*` = WHERE (multi-value), the `Epic`
  group workstream = WHAT; D9 epic/sub-issue discipline whenever WHERE has ≥2 values.
- STOPs per D12: `blocked`/`needs-owner` label + comment; label removed when resolved.
- MCP quirk encoded in the skill: `save_issue.labels` REPLACES the full label set — always
  read current labels first and resend the union; relations (`blockedBy`, `relatedTo`) are
  append-only by contrast.
- **Embeds the "Linear rich text" reference** (research 2026-07-08) — the markdown dialect
  for descriptions/comments (full content in the plan, Task 7).
- Every work item gets a `docs/tasks/` mirror (see §4) — a repo-side record, not a second
  board: Linear stays the status authority; the mirror updates at create/close only.

### 2.3 `sdlc-python` and `sdlc-electron` (adopted; `sdlc-go` deferred — D5)
- SHARED-LOOP regions kept **verbatim-identical** across the two adopted skills (loop parity
  enforced by script, §5).
- Shared adaptations (identical in both files): gate runner path
  `uv run .claude/scripts/run_gates.py <stack>`; `ledger_dir` → `docs/work/` with D8 naming;
  ticket refs are `OME-N` (`Refs: OME-N` as the card's `commit_refs`); sibling references
  name only the adopted pair; card-missing wording → restore from git.
- `sdlc-electron` extends the source sdlc-react stack sections: main/preload/renderer
  process model, both-side IPC contract testing (rule S2), strict-TS at IPC boundaries,
  the **official Electron security checklist encoded** (contextIsolation/sandbox on,
  nodeIntegration/webSecurity-off forbidden, IPC sender validation, permission handler +
  CSP, navigation/window-open restriction, shell.openExternal hygiene, https-only,
  current Electron; external HTTP in main only), a11y gate retained (rule S1).

### 2.4 `working-in-this-repo` (update, same change)
§6 branch/PR rules → Linear flow (branch `OME-N-<desc>`, `Refs: OME-N` in commit body);
pointers add task-management + sdlc-* skills and the two cards; routing table gains the
`app/*` label per app.

## 3. Cards

### 3.1 `.claude/task-board.local.md` (committed)
Frontmatter: `system: linear`, workspace `openmined`, `team: {key: OME, id}`,
`project: {name, slug, id}`, states map (existing: todo / in_progress / in_review / done /
triage / backlog), label registry (`apps:`, `pkgs:`, `coms:`, `repo:`, `stop:` (blocked /
needs-owner), `types:` group, `who_acts:` group — name→ID), priority map, transport
(`mcp: plugin:linear`, `fallback_key_source: ~/.config/linear/.env`), `close_template`.
Body: ticket rules (D9 label discipline, D11 project rule, D12 STOP rule, Asana-URL rule,
mirror-file rule, com-labels-are-product-concepts, labels-REPLACE quirk).

### 3.2 `.claude/sdlc.local.md` (committed)
As previously specified: stacks `aigateway` + `scoreboard` (python; ruff/format/pyright/
pytest-cov gates; aigateway adds the enterprise-import guard), `commit_refs: "Refs: OME-N"`,
`ledger_dir: docs/work/`, companion_skills (tortoise-dev mandatory for schema/migrations),
per-stack invariants (aigateway credential rules; scoreboard artifact allowlist).

## 4. Mandatory CLAUDE.md "AI SDLC" section (replaces "Git Workflow" Asana rules)

0. **95% confidence gate — TOP RULE.** Never write, assert, or implement anything you are
   not ≥95% confident is both correct AND wanted. Below 95% → STOP and ask first. Applies
   to every rule below and every artifact: code, work items, docs, diagrams.
1. **Work item first.** All work starts as a Linear issue (`OME-N`) in the Engineering team,
   attached to the **😱 ScreamingFace V1** project, carrying its labels (workstream from the
   `Epic` group; `app/*`/`pkg/*` or `repo` for landing; one who-acts; one `actor` —
   agentic|human) plus a mirror `docs/tasks/YYYY-MM-DD-<name>.md`. At finish, close status
   in BOTH.
2. **Work ledger.** Every finished unit has `docs/work/YYYY-MM-DD-<ticket-id>-<desc>.md`
   (created at work start, outcome filled at finish — see the sdlc skills).
3. **Spec before plan, plan before code.** `docs/spec/` artifact required before planning;
   `docs/plan/` artifact required before implementation. Prefer `/superpowers`
   (brainstorming → writing-plans) or similar. Never plan or implement without them.
4. **Diagrams.** Propose the diagramming plugin
   (https://github.com/sergio-bershadsky/ai/tree/main/plugins/diagramming) when it's absent;
   assets live in `docs/diagrams/` (SVG source + PNG).
5. **Branches/commits.** Branch `OME-N-<desc>` (e.g. `OME-12-fix-refresh`). Conventional
   commits; body carries `Refs: OME-N`; never `Co-Authored-By`; never commit to `main`.
6. **Asana boundary.** Asana is READ-ONLY product/marketing input (`asana-product` skill).
   Technical work items never go to Asana.
7. **Cross-cutting work (D9).** Touching ≥2 apps/packages → epic with its workstream
   (`Epic` group) label + all affected `app/*`/`pkg/*` labels, one sub-issue per affected
   app/package. Never a single-app filing, never one mega-ticket.

## 5. Agents & scripts

- `.claude/agents/sdlc-unit-executor.md` — executes ONE `OME-N` work item through the
  stack's SDLC loop; STOP conditions compile to the D12 labels (`blocked` / `needs-owner`)
  + a comment via the Linear MCP; same JSON return contract and prohibitions as the source
  agent.
- `.claude/agents/ticket-filer.md` — validates every entry against the card's label/priority
  registry, then files via the Linear MCP (`save_issue` with team + project + labels);
  all-or-nothing; returns `identifier | title | URL | state` table.
- `.claude/scripts/run_gates.py` — adopted near-verbatim (card-driven, PEP-723 uv script).
- `.claude/scripts/check_loop_parity.py` — `SKILLS = ["sdlc-python","sdlc-electron"]`, paths
  under `.claude/skills/`; extended per stack added.
- `.github/workflows/repo-checks.yml` — path-filtered to `.claude/skills/sdlc-*/**` +
  `.claude/scripts/**`; runs loop-parity.

## 6. Implementation phases

1. **Bootstrap Linear** *(DONE 2026-07-08)* — Linear MCP activated (D4); taxonomy locked
   (D10 align + extend) and labels in place; adoption epic **OME-358** filed with phase
   sub-issues OME-359/360/361/362 under 😱 ScreamingFace V1. IDs in
   `.docs/linear-bootstrap-ids.md`. Owner cleanup pending: delete obsolete trial labels
   (`com/*`, `type` group, plain `blocked`) in the Linear UI.
2. **Cards + docs tree + CLAUDE.md** — both cards; docs/tasks + docs/work (+TEMPLATE);
   CLAUDE.md §4 rules; dogfood mirror/ledger for the epic.
3. **Skills** — `asana-product`, `task-management` (Linear+MCP, incl. the rich-text
   reference), `sdlc-python`, `sdlc-electron`, `working-in-this-repo` update.
4. **Agents + scripts + CI** — §5 items; parity green.
5. **Backfill work items** — `repo`: name lock-down/reservation, GH Pages decision;
   `app/scoreboard`: portal stopgap revisit; `pkg/url4-python-sdk` + `com/url4`: url4 SDK
   extraction epic (`app/desktop` / `app/cli` epics wait for name lock).

## 7. Out of scope / deferred

- `sdlc-go` (until a Go component exists — D5).
- `app/desktop` / `app/cli` labels and epics (until package names locked).
- Migration of historical Asana SF-N tickets into Linear (not requested).

## Open questions (none blocking)

- Whether `repo-checks.yml` also runs actionlint — nice-to-have, decide in implementation.

Confidence: ≥95% on design correctness/completeness given locked decisions D1–D12.

## Decisions superseding (2026-09-22) — epic first

These decisions sit on top of the 2026-07-08 record. They do not rewrite it. The 2026-07-15
reconciliation (`OME-443`) already deleted the `Epic` label group that D10 treated as the
workstream axis, and the live `type` group is `decision` / `task`. "Epic" below means a
Linear **parent issue**, not that deleted label group.

| # | Decision | Choice |
|---|---|---|
| D14 | Organizing unit | The **epic** (a parent issue) is the primary organizing unit. It carries priority, one landing leaf, one actor, and a rationale in the body. Every other issue has `parentId` set to an epic. Agents file leaves only; they do not file orphans and never auto-create epics (see D16). |
| D15 | Milestones | Milestones are an **optional** phase grouping above epics. They are not required. The legacy sprint milestones are not the backbone; retiring the stale launch milestones is an owner action after open children sit on an epic. |
| D16 | No fitting epic | The agent **proposes** an epic and states plainly that it may not create one on the user's behalf (*"this is a proposed epic for this work — suggest edits or confirm"*). It creates the epic **only with the user's direct consent** — never automatically. On consent: create it in the **Triage** state with the rationale in its body and the `[EPIC]` title suffix, and tag Irina Bejan (`irina@openmined.org`) and Kevin McDonough (`kevin@openmined.org`) in a comment for scope review and approval. The leaf is filed under the proposed epic and the PR proceeds — scope approval is asynchronous and does not block (reparent later if redirected). Irina doubles as product reviewer, so both the prioritized and not-yet-prioritized paths tag Irina and Kevin. (Revised 2026-09-23, `OME-1262`, superseding the earlier hard-stop / human-authors-only rule.) |
| D17 | Epics are queryable | The owner created a standalone `epic` workspace label (id `fa574829-3329-4c84-831f-42a23cb74164`, registered in the board card 2026-09-23) plus a saved **Epics by priority** view (filter `label = epic`). **Every epic carries the `epic` label** — agents apply the existing label via `addLabels`; they do not mint it. |
| D18 | No-epic park state | D12's `blocked` and `needs-owner` labels are not live, and this decision does not add workflow states. The no-epic stop does not file. An already-filed issue with no parent epic moves to **Triage** plus a comment. D9 still holds: work spanning ≥2 landings is one sub-issue per landing under the epic. |
| D19 | When the issue is filed | The Linear issue is created **when the pull request is opened — not at the moment work starts, and not on a commit or a new branch** — and only after the agent asks the user to confirm it (title, parent epic, labels, priority). A session opening, a commit, or a pushed branch is not a reason to file; exploration, drafting, committing, and pushing a branch need no issue. `Refs: OME-N` goes in the PR body. This narrows filing to the point a change is proposed for merge. (2026-09-23, superseding the earlier first-commit trigger, `OME-1262`.) |
| D20 | Epic naming & classification | Epic titles end with the suffix ` [EPIC]` (never an `EPIC:` prefix or an `(epic)` suffix). Every epic is attached to the project, carries the standalone `epic` label, and carries **exactly one classification** label — `tech-debt` / `product-feature` / `infra` (EPIC-only workspace labels; ids in the card's `labels.classification`). Pure process/meta epics may skip the classification. Agents apply existing labels; they never mint them. (2026-09-23, `OME-1259`/`OME-1262`.) |
| D21 | Self-assign on creation | Every issue **and** every epic is self-assigned by its creator at creation (`assignee: "me"`) — nothing is filed unassigned, **except a `bug`-labeled issue (see D22), which is left unassigned.** `"me"` resolves to whoever is currently authenticated to the Linear MCP (the person running the session), not a hardcoded default. Reassigning to a different owner is a later, deliberate act. Applies to both agent-filed leaves and consented proposed epics. (2026-09-23, `OME-1262`.) |
| D22 | Bug exception to epic-first | The **only** exception to epic-first (D14/D16): an issue labeled `bug` need not belong to an epic. It is filed with **no parent**, in the **Triage** state, **unassigned** (bugs do not self-assign, cf. D21), with Irina and Kevin tagged in a comment for review. It still carries a landing leaf + `actor` and a `docs/tasks` mirror. Everything that is not a `bug` goes under an epic and self-assigns. (2026-09-23, `OME-1262`.) |
| D23 | Ledger keyed by slug, not ticket-id | D19 (file at PR-open) left the work-ledger un-nameable, since D2/D8 baked `OME-N` into the filename. **The ledger is created at work START as `docs/work/YYYY-MM-DD-<slug>.md`** (slug = branch description) with frontmatter `ticket: unfiled`, **backfilled to `OME-N` at PR-open.** Ledger identity ≠ Linear identity. Supersedes the `<ticket-id>` naming in §4 rule 2 and the D8 card rule. (2026-09-24, `OME-1262`.) |
| D24 | Branch naming | Branches use `<slug>` at work start (no `OME-N` yet) and are **renamed to `OME-N-<desc>` at PR-open** (`git branch -m`) once the issue is filed, so the branch-name GitHub/Linear automation still links. `Refs: OME-N` lives in the PR body, not commits. Supersedes the `OME-N-<desc>`-from-the-start branch rule. (2026-09-24, `OME-1262`.) |
| D25 | Universal filing; executor input | PR-time filing (D19) applies to **all** work, including batch execution. `sdlc-unit-executor` no longer takes a pre-existing `OME-N`: its input is a **unit of work + parent epic**, and **dispatching it on those IS the user's confirmation** to file (it is headless, never asks mid-run). It files the leaf at PR-open under the pre-approved epic, renames the branch, and backfills the ledger; pre-filing STOPs return `blocked` in the return value (no issue to annotate yet). Supersedes the §5 "executes ONE `OME-N`" description. (2026-09-24, `OME-1262`.) |
| D26 | ticket-filer repurposed | Under universal PR-time filing there is no batch of leaves to file up front. `ticket-filer` becomes the mechanical **single-leaf PR-open filer**: one implemented leaf → validate against the card → file under its epic (self-assigned, In Progress) → return the identifier for the PR body; the caller backfills the ledger + creates the mirror. Bug path preserved (no parent/assignee, Triage, reviewers tagged). Supersedes the §5 all-or-nothing batch description. (2026-09-24, `OME-1262`.) |

Detailed in `docs/spec/2026-09-24-ledger-slug-pr-time-filing-reconciliation.md`.

Tracked as epic `OME-1259`. The process-doc unit is `OME-1262`.
