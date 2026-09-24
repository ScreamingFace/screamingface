---
description: Use for ANY task/ticket work — creating, triaging, planning, implementing, or closing work items. All units of work are Linear issues in the team + project named in .claude/task-board.local.md. Defines epic-first filing (every leaf under an epic; no fitting epic → the agent proposes one and creates it only with the user's direct consent, parked in Triage with Irina + Kevin tagged for approval; the issue is created when the PR is opened and only after the user confirms it — not at work start, and not on a commit or a new branch), the label taxonomy (single-select landing groups + actor / who-acts / type), STOP handling, optional milestones, close discipline, docs/tasks mirrors, the Linear MCP command crib, and the Linear rich-text dialect. Invoke at session start, before starting any unit of work, and before filing or closing an issue.
user_invocable: true
---

# Task Management — Linear work items

**Announce at start:** "Using the task-management skill — the Linear work-item lifecycle."

> This skill is workspace-agnostic. Every concrete name — team, project, issue-key prefix,
> the label groups and their leaves, milestone/sprint names, status names, the
> `close_template` — resolves from **`.claude/task-board.local.md`** (the "card"). Where this
> doc shows an example set, it is illustrative; the card is authoritative.

## Card resolution — before anything

Read `.claude/task-board.local.md` (at the **repo root** `.claude/`, not beside this skill). **Missing → HARD STOP:** tell the user the card is gone
and stop — never guess team, project, or label IDs. `{{…}}` placeholders resolve from the
card; its body rules bind alongside this skill.

**Transport: the Linear MCP plugin ONLY** (`mcp__plugin_linear_linear__*`; activate via
`/mcp`). **API tokens and raw GraphQL are FORBIDDEN.** Agents act **only on issues** — create
issues; edit an issue's title, applied labels, status, priority, milestone, assignee,
relations, and comments. **Agents do NOT create, rename, delete, reparent, or edit labels** —
all label management (and teams, workflow states, templates, integrations, and issue
deletion) is an **OWNER action in the Linear UI**. When one is needed, hand it over with
precise steps.

Single holder = the card's team + project (`{{team}}` · `{{project}}`). No parallel boards.
Session todos are fine for intra-session tracking; anything that outlives the session is a
Linear issue. The `docs/work/` ledger is the how/audit record; the issue is the what/status
record — they cross-reference, never duplicate. Every issue gets a repo mirror
`docs/tasks/YYYY-MM-DD-<name>.md` (frontmatter: id, linear_url, asana_url?, status, type,
priority, labels, created, closed). **Linear is the status authority.**

## Label taxonomy

Labels are organized as **single-select groups** — one leaf per group per issue, enforced by
Linear — and are **two levels deep**; a sub-component is a slash inside the leaf name
(`desktop/eval-runner`), NOT a real sub-group. The exact groups and leaves live in the card.
**Agents never mint labels.** Need a new leaf? Propose it to the project lead, who creates it
in the UI and registers it in the card in the same change — then apply it to issues.

- **Landing — WHERE the work lands. MANDATORY on every issue and epic.** One or more top-level
  groups partition work by landing type (application vs package vs cross-cutting, etc.). Pick
  **exactly one leaf**, normally from one group — there is no default: an issue filed with no
  landing/component leaf is a validation failure, not a guess. Leaves carry UI descriptions —
  trust them. Work spanning ≥2 components is an epic + one sub-issue per component (each with its
  single leaf), never two leaves on one issue.

  > **Example (this workspace's card):** groups `app` / `pkg` / `cross-unit`, e.g.
  > `app › desktop`, `app › aigateway`, `app › screamingface-engine`, `pkg › client-sf`,
  > `pkg › url4-sdk`, `cross-unit › repo-dev-processes`. Your card defines the real set.

- **`actor` — `agentic` | `human`.** Who executes. Required on **agent-executed / SDLC**
  items; human-owned roadmap tickets may carry just the landing leaf + assignee (actor = the
  assignee).
- **`who-acts` (one, on SDLC items):** `design-session` (direction fork — agents prepare,
  never decide) · `autonomous` (agent-runnable end-to-end) · `deferred` (gated on a named
  precondition — state it in the body).
- **`type` (one, optional):** `decision` (a locked decision, not code) · `task`
  (mechanical/housekeeping/research — no product-behaviour change). Extend only via the card.
- **STOP is a STATUS, not a label:** move to the **Blocked** state (hard question pending) or
  **Needs Owner** state (only a decision/visual check pending) + comment the exact question;
  move back when resolved.
- **Blockers are RELATIONS + the `blocked` label:** if a ticket waits on another, set a
  **blocked-by** relation to the named blocker AND apply the `blocked` label. Never bare — a
  `blocked` with no named blocker is a validation failure. The dependency graph must be real.
- **Priority** (Linear ints): 1 Urgent (launch-blocking) · 2 High · 3 Medium · 4 Low. If the
  workflow has a dedicated "queued next" state, use that for ordering — not priority — and
  keep the two distinct. Agent proposes; owner's setting wins.

**Cross-cutting rule:** an issue carries **at most one** landing leaf. Work spanning ≥2
landings → a parent **epic** + one **sub-issue per landing** (each with its single leaf).
Two leaves from one group are rejected by Linear — that's the signal to split.

## Epic first

An **epic** is a Linear parent issue. It is the unit of prioritization. Priority on the epic is the signal for what the team is actually working on (the owner sets it; the highest-priority open epics are the active set). Milestones are an optional phase grouping above epics. They are never required, and new work does not slot into the legacy sprint milestones.

- **Epics are human-authored — the agent proposes, never creates one on its own initiative.** When no existing epic fits, the agent drafts a **proposed epic** (title, rationale, scope) and says plainly: *"I'm not allowed to create an epic on your behalf. This is a proposed epic for this work — suggest edits, or confirm and I'll create it."* The agent creates the epic **only with the user's direct consent**, never automatically.
- **On consent, create the proposed epic in the card's `Triage` state** (with the rationale in its body and the `[EPIC]` title suffix), then **tag Irina (`irina@openmined.org`) and Kevin (`kevin@openmined.org`) in a comment** for scope review and approval. The product reviewer is Irina (she doubles as product), so both the not-yet-prioritized and already-prioritized paths tag Irina and Kevin.
- **The work is not blocked on that approval.** File the leaf under the proposed epic and open the PR now; Irina/Kevin's scope sign-off is asynchronous. If they reject or redirect the scope, reparent the leaf later.
- **Every agent-filed leaf sets `parentId` to an epic** — an existing one, or the proposed one the user just consented to. No orphan tickets. (`blocked` is a real label, applied only with a named blocker + a blocked-by relation; `needs-owner` is not live.)
- **The one exception — bugs.** An issue labeled `bug` is exempt from epic-first: a bug fix may be filed with **no parent epic**. It is filed in the `Triage` state with **Irina + Kevin tagged in a comment for review**, and — unlike every other issue — is **left unassigned** (`bug`s do not self-assign). It still carries a landing leaf + `actor` and gets a `docs/tasks` mirror. Everything that is not a `bug` goes under an epic and self-assigns.

Cross-cutting work (≥2 landings) is still an epic plus one sub-issue per landing. Single-landing work is a leaf under an epic too.

## Two ticketing modes

- **Human-filed (roadmap / epic / decision):** use the Linear **issue templates** the card
  lists (typically a default Roadmap template, a Cross-cutting Epic template, and a Decision
  template). The template supplies the body shape and preset labels; the filer adds the
  landing leaf, priority, and assignee. A milestone is optional.
- **Agent-filed SDLC unit:** filed through the MCP per this skill (deliberately **no UI
  template** — the skill is the template). Carries a landing leaf + `agentic`|`human` + a
  `who-acts` leaf. **Filed when the PR is opened — not at work start, and not on a commit or a
  new branch — after the user confirms it.** Runs ledger → RED → GREEN → gates → commit → push
  freely, then at PR-open files the issue and puts `Refs: <issue-id>` in the PR body, and the
  close-comment at finish.

## Naming & board conventions

- **Title = imperative summary only.** Do **not** prefix titles with the issue ID — Linear
  shows the ID natively beside every issue. No legacy component prefixes either; the landing
  leaf carries the component. Leaf names are lowercase-kebab.
- **Epics organize the board.** Every leaf has `parentId` set to an epic. A milestone is
  optional, and only when the project lead is grouping a phase of epics. Do not assign the
  legacy sprint milestones.
- **Epic title ends with ` [EPIC]`** — a suffix, never an `EPIC:` prefix or `(epic)`.
- Every issue: one landing leaf + priority. An epic also (a) is attached to the project,
  (b) carries a rationale in the body, (c) carries the mandatory `epic` label, and
  (d) carries exactly **one epic-classification** — `tech-debt` / `product-feature` / `infra`,
  the single-select leaves of the `epic` group; that leaf IS the epic marker. Only epics carry it —
  non-epics carry a component/landing leaf instead. See `labels.classification`
  in the card.
- **Self-assign on creation — mandatory (except bugs).** Every issue **and** every epic is
  assigned to its creator at creation time (`assignee: "me"`); nothing is filed unassigned —
  **except a `bug`-labeled issue, which is deliberately left unassigned.** `"me"` resolves to
  **whoever is currently authenticated to the Linear MCP** — the person running the session,
  not a hardcoded default. Reassign to a different owner only as a later, deliberate act.

## Lifecycle & statuses

```
PLAN (docs/plan) ─▶ EPIC (already exists, or the agent proposes one and creates it with the user's consent)
─▶ TICKETS under that epic (one per SDLC unit; multi-landing → one sub-issue per landing)
─▶ OWNER REVIEW (scope/priority/labels) ─▶ IMPLEMENT (sdlc-* loop) ─▶ CLOSE ─▶ NEXT
```
The team's workflow states (exact names per the card) follow the shape: **incoming/backlog →
queued-next → in-progress → in-review → done**, plus whatever STOP signal the card actually
registers, and terminal **Canceled** / **Duplicate**.

**When the issue is created — when the PR is opened, with the user's confirmation.** Do not
file at the instant work starts, and **do not file on a commit or a new branch** — a session
opening, a commit, or a pushed branch is not a reason to file. Explore, draft, commit, and
push a branch freely first. The Linear issue is created **when you open the pull request** —
and **only after you ask the user to confirm** it (title, parent epic, landing leaf,
priority). Sequence: work → commit → push branch → confirm → create the issue under its epic
(get `OME-N`) → open the PR with `Refs: OME-N` in its body. Commits and branches need no
issue; only opening a PR does. The `docs/tasks/` mirror is created with the issue. Epic-first
still holds: no fitting epic → propose one and, with the user's consent, create it in Triage
(Irina + Kevin tagged for approval); then file the issue under it. The work does not block on
that approval.

**No-epic stop:** do not file. The card is authoritative for how an already-filed orphan is
parked. On this board that park state is **Triage** plus a comment naming the missing epic.
Do not use `blocked` for the no-epic case — `blocked` is for a real named blocker (label +
blocked-by relation); `needs-owner` is not live. This change does not add workflow states.

**If GitHub status automation is enabled** (see the card): opening the PR moves the issue to
*in-review*, merging moves it to *done* (branch names follow `…/<issue-id>-…`;
`Fixes <issue-id>` in the PR body also closes it). In that case you manually set only the
*queued-next* and *in-progress* states (in-progress when the issue is filed at PR-open) and the STOP states —
don't hand-move the in-review/done transitions the PR will drive.

## Close discipline

Even with GitHub auto-done, an issue is only properly closed with the card's `close_template`
filled: commit shas + messages, gates that ran (test counts/baselines), ledger path(s),
deviations, owner-visual-check notes. Long gate output in a `+++ Gates … +++` collapsible.
Then close the `docs/tasks/` mirror. A merge without the close-comment is an incomplete close.

## Command crib (Linear MCP)

- **Create a leaf:** `save_issue {team: "{{team}}", project: "{{project.slug}}", title: "<imperative summary>", description, labels: ["<landing leaf>", ("agentic"|"human")?, ("autonomous"|"deferred"|"design-session")?], priority, assignee: "me", parentId: "<epic id>"}` → returns the issue ID + URL. NO id on create; NO issue-ID in the title. **`parentId` and `assignee` are required** — self-assign (`assignee: "me"`), never file unassigned. **Exception:** a `bug`-labeled issue may omit **both** `parentId` and `assignee`; file it `state: "Triage"` (unassigned) and comment-tag Irina + Kevin. Omit milestone unless the card's project lead has named an optional phase milestone. Agents do not create the parent epic.
- **Move state (only the non-automated ones):** `save_issue {id, state: "<queued-next>"|"<in-progress>"|"<Blocked>"|"<Needs Owner>"}` (use the card's exact state names)
- **STOP:** `save_issue {id, state: "<Blocked>"|"<Needs Owner>"}` + `save_comment {issueId, body: "<exact question>"}`
- **Blocker relation:** `save_issue {id, blockedBy: ["<issue-id>"]}` (append-only; `removeBlockedBy` to clear)
- **Close:** `save_comment {issueId, body: <close_template>}` (a PR merge usually sets done)
- **List/find:** `list_issues {project, label?, state?, query?, parentId?}` · `get_issue {id}` (list truncates descriptions ~500 chars — use `get_issue` for full bodies/relations)
- **New leaf:** OWNER UI action — agents don't create labels. Propose it to the lead; they create it and register it in the card, then you apply it via `save_issue.labels`.

**MCP quirks:**
- `save_issue.labels` **REPLACES the full set** — `get_issue` first, resend the union.
  Relations (`blockedBy`, `relatedTo`, `links`) are append-only.
- Two leaves of one group are rejected/collapsed — the split signal.
- Raw markdown, **literal newlines** — never `\n` escapes. `assignee` = `"me"`/name/email.

## Linear conventions we rely on (owner-configured, not MCP; see the card)

- **Issue templates** for the human-filed modes (Roadmap default · Cross-cutting Epic · Decision).
- **GitHub integration** auto-transitioning status (in-review on PR open, done on merge), where enabled.
- **Single-select label groups** enforcing one leaf per axis (the cross-cutting split signal).
- **Label descriptions** documenting each leaf in the picker — keep them current.

## Linear rich text

Headings `#`–`####`; `**bold**` `_italic_` `~~strike~~` `` `code` `` (no underline);
`-`/`1.`/`- [ ]` lists; `>` quote; **`+++ Title … +++`** collapsible (logs/gates); fenced
code (` ```mermaid ` renders); `---`; GFM tables; `:emoji:`; **no HTML**. **Refs have
side-effects:** `@name` notifies; an `@`-prefixed ID, issue URLs, AND a bare issue ID become
issue embeds + can create relations — wrap IDs in backticks for a plain reference. Bare
YouTube/Loom/Figma/Docs URLs auto-embed; `[text](url)` keeps a link.

## Anti-patterns — STOP

| Thought | Reality |
|---|---|
| "Session todo is enough." | Outlives the session? Linear issue, under an epic. |
| "File now, parent later." | No fitting epic → propose one, get the user's consent, create it in Triage (Irina + Kevin tagged), then file the leaf under it. |
| "I'll just create the epic." | Never on your own initiative. Say "I'm not allowed to create an epic on your behalf — this is a proposed epic; confirm and I'll create it." Create only on direct consent. |
| "One big issue for the plan." | Epic parent + SDLC-unit sub-issues. |
| "Two landings, one leaf." | Group is single-select — epic + one sub-issue per landing. |
| "Prefix the title with the issue ID." | Don't — Linear shows the ID; title is the summary. |
| "Add a bare `blocked` label." | `blocked` is allowed only WITH a named blocker: apply the label AND set the blocked-by relation. |
| "I'll hand-set in-review / done." | If GitHub automation is on, the PR does that — set only queued-next / in-progress / STOP. |
| "Close it, code's merged." | Merge ≠ close-comment. File commits+gates+ledger. |
| "design-session, answer's obvious." | Prepare a proposal; owner decides. |
| "I'll create the label I need." | Agents never create labels — propose it; the lead adds it in the UI + card, then you apply it. |
| "MCP can't — use the API key." | FORBIDDEN. Uncovered ops are owner UI actions. |
| "Set labels without reading current." | `labels` REPLACES — read, union, resend. |
