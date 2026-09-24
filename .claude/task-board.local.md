---
system: linear
workspace: openmined
transport: "Linear MCP plugin (plugin:linear) — the ONLY transport; PRECONDITION: activate via /mcp. API tokens/GraphQL FORBIDDEN; MCP-uncovered ops (label/team/state management) are owner actions in the Linear UI"
team: { key: OME, name: Engineering, id: "5f4d721f-4452-4ed1-990a-7cdbcd923508" }
project: { name: "😱 ScreamingFace V1", slug: screamingface-v1-27666092fc7f, id: "7cbe5759-cc07-476d-b81e-da05b6b2d4d7" }
states:
  todo: "88de5fec-8ce3-4172-b462-6c418837accf"
  in_progress: "03621515-86a4-4669-aad7-5467a23505f1"
  in_review: "62b4c1a3-752f-456b-bdf6-7ce484959e5d"
  done: "699b96ac-cd89-42db-a717-4f8b291a7388"
  triage: "a6fc6a19-f6fd-4fda-baf6-2d26cc54adae"
labels:  # Snapshot of live Linear labels (team Engineering). Reconciled 2026-09-24; see git log for deltas.
  # Landing axis: Linear groups product areas under parent groups (app / pkg / cross-unit).
  # There is NO "Epic" workstream group; the component IS the app/* or pkg/* landing label.
  landing:
    # ── app ──
    "aigateway": "f92de050-b7ec-41fe-a14a-d30c0d0be267"              # parent: app
    "scoreboard": "3f8aa7fc-e9a0-461f-8a6b-0bf2dd7cf4d9"            # parent: app
    "screamingface-engine": "cc1ac9b3-45af-4bec-a112-560ad1f52680"  # parent: app — the ScreamingFace Engine
    "url4-engine": "b9bdd9c0-b03b-47e0-86c9-b3f45305212a"           # parent: app — url4 grammar/parser/DAG exec
    "desktop": "cef9d753-9675-4f7d-8ae7-afc7af802887"              # parent: app
    # ── pkg ──
    # NOTE: app `url4-engine` (b9bdd9c0) and pkg `url4-sdk` (05d3d132) are DIFFERENT labels — the two
    # names were swapped historically; resolve by id, never conflate.
    "client-sf": "8d3dd8bd-5365-4ab7-90d5-9e5317cf3157"            # parent: pkg — screamingface Python client + notebooks
    "url4-sdk": "05d3d132-d508-4540-be46-4d10303e117a"             # parent: pkg — url4 engine client package
    # ── cross-unit ──
    "repo-dev-processes": "220d479a-98b5-4b94-95ee-92635db5f0ae"    # parent: cross-unit
    "auth+subsidies": "8c34e37b-f78f-4983-ae62-8f97ba26c28f"        # parent: cross-unit
    "analytics": "ff4eeff4-5bca-48c7-bd7c-28702e39855a"            # parent: cross-unit
    # ── ungrouped ──
    "repo": "89353e43-30b4-4e4b-b0a6-d781f9dcfebc"                  # ungrouped (process; coexists with repo-dev-processes)
    "syft-station": "af936751-944c-439e-a460-33b8107cc57f"          # ungrouped
    "syft-space": "55b0b894-9717-4a82-9e40-aba3d01922cd"           # ungrouped
    # ── retired (still in Linear, applied to old issues → resolvable, do NOT apply to new work) ──
    "url4-cloud": "295a9fe1-826e-49f8-8f11-e4f438aa27a1"           # parent: app — legacy Engine name; issues merged onto screamingface-engine
    "desktop/benchmarks": "53bb9d19-95a2-4479-9acd-6ea6423ae251"    # parent: app — RETIRED (merged onto desktop)
    "desktop/ensemble": "d55512f6-389d-4fc4-877a-6a6be434c4c1"      # parent: app — RETIRED (merged onto desktop)
    "desktop/eval-runner": "543fbbde-bdd5-430b-8ecd-26f33628bdc3"   # parent: app — RETIRED (merged onto desktop)
    "desktop/results-runs": "d0e1871e-db73-4ba6-bc7a-fcbfde515e40"  # parent: app — RETIRED (merged onto desktop)
  who_acts:  # Linear group "who-acts" — one per issue (members verified 2026-07-15)
    "design-session": "b23148b7-7779-415d-b1c8-5480fa967067"
    "autonomous": "6c277f7f-e4b3-41c6-b1ba-406781bb84ed"
    "deferred": "24c84d24-251d-42d0-ba0f-d0c174a68809"
  actor:  # Linear group "actor" — MANDATORY, one per issue (D13) (members verified 2026-07-15)
    "agentic": "836136d4-994f-457a-9e5e-7f14cf15b4f1"
    "human": "6bb84ba1-b63e-43d6-a061-b80db8565ecf"
  type:  # Linear group "type" — optional tagging (replaced the former Bug/Feature/Improvement)
    "decision": "89f24a1e-50fe-43c6-8ba9-bcf0f25d6ab7"  # a LOCKED decision (contract frozen), not code
    "task": "5fc84240-25d2-4893-85b7-9e12bb0db207"       # mechanical/housekeeping/research — no product behavior change
  epic:  # standalone workspace label (NOT under the type group) — MANDATORY on every epic
    "epic": "fa574829-3329-4c84-831f-42a23cb74164"  # created 2026-09-23; apply via addLabels to every epic (parent) issue
  classification:  # EPIC-ONLY labels — exactly ONE per epic (process/meta epics may skip). standalone workspace labels
    "tech-debt": "76c260e6-73c2-41a5-9f69-b226a4c2810f"        # work that is tech debt
    "product-feature": "7a4418fd-1ceb-4822-b342-4d4e56cd096f"  # a new product feature
    "infra": "22a133e3-7844-4d62-bfe1-a449baa785ed"            # internal infrastructure
  # ── Notes ─────────────────────────────────────────────────────────────────────────────────
  #   STOP labels `blocked ⛔` / `needs-owner` are NOT live: a no-epic stop parks the issue in Triage
  #   with a comment (D18, OME-1259), never a label; never add workflow states. This card is a live
  #   snapshot, not a changelog — full label history (renames, deletions) is in git.
  # who_acts/actor `group:` parent IDs from the prior card were dropped (unverified + unused for
  # filing, which resolves by member label). Re-add if a group-level operation ever needs them.
priority: { P1: 2, P2: 3, P3: 4 }  # Linear ints; 1 (Urgent) reserved for incidents
# Epic priority is the same field. The epics the team is actually working are the
# highest-priority open epics (owner-set). There is no separate P0 integer.
reviewers:
  engineering: kevin@openmined.org   # Kevin McDonough, head of engineering
  project_lead: irina@openmined.org  # Irina Bejan
  product: irina@openmined.org       # Irina doubles as product reviewer (confirmed 2026-09-23, OME-1259)
close_template: |
  Commits: <sha> <message>[, …]
  Gates: <run_gates.py summary / test counts>
  Ledger: docs/work/<file>.md
  Deviations: <none | list>
  Owner-verify: <none | what to check visually>
---

# Ticket rules (bind alongside the task-management skill)

## Epic conventions (2026-09-22, OME-1259)

- An epic is a Linear **parent issue**, attached to the project (`{{project}}`). It carries
  priority, one landing leaf, one actor, and a rationale in the body. It **must** carry the
  standalone `epic` label (`labels.epic` above) — apply it via `addLabels`.
- **Epic title ends with ` [EPIC]`** (a suffix). Do NOT use an `EPIC:` prefix or an
  `(epic)` suffix — normalize to ` [EPIC]`.
- **Every epic carries exactly ONE classification label** from `labels.classification`:
  `tech-debt`, `product-feature`, or `infra` (EPIC-only). Pure process/meta epics
  (e.g. `OME-1259`) may skip it. Agents apply the existing label; they do not mint it.
- Demoting an epic to a sub-issue reverses all three: remove `epic` + the classification
  label, strip the ` [EPIC]` suffix, and set `parentId` to the new epic.
- Every other open issue has `parentId` set to an epic. Agents do not file orphans and never
  auto-create epics.
- **The one exception is a `bug`.** An issue labeled `bug` need not belong to an epic — file
  it with no parent, in the **Triage** state, with Irina + Kevin tagged in a comment for
  review, and **left unassigned** (bugs do not self-assign). It still carries a landing leaf +
  `actor`. Anything that is not a `bug` goes under an epic and self-assigns.
- No fitting epic: the agent **proposes** one and says plainly it may not create an epic on
  the user's behalf (*"this is a proposed epic — suggest edits or confirm"*). It creates the
  epic **only with the user's direct consent** — never automatically. On consent: create it
  in the `Triage` state (rationale in the body, ` [EPIC]` suffix) and tag Irina + Kevin
  (`reviewers.project_lead` + `reviewers.engineering`) in a comment for scope approval. File
  the leaf under it and open the PR — scope approval is async and does not block (reparent
  later if redirected). Irina doubles as product (`reviewers.product`), so both paths tag
  Irina and Kevin.
- When a ticket is added under an epic, move it out of Triage to **Backlog** (unless it is
  actively started/in-review) — Triage is the *no-epic* park state, not a resting state for
  a parented ticket.
- Milestones are optional. Do not put new work on the legacy sprint milestones (Walking
  Skeleton, Week 1, Week 2, Testers, Fusion Monsters Launch, Public Launch). Retiring the
  two stale launch milestones is an owner action (`OME-1260`), after open children sit on
  an epic.
- Saved view **Epics by priority** (filter `label = epic`, group by priority then status)
  is an owner UI action (`OME-1260`). It is the at-a-glance board.
- No-epic park state is **Triage** (`states.triage`) plus a comment. Do not apply
  `blocked` or `needs-owner`.

- Every work item: team Engineering + project 😱 ScreamingFace V1 (D11) + a **component/landing
  label — MANDATORY** (exactly one leaf from `landing:` — `app/*`/`pkg/*`, or `repo` for pure
  process work; epics and `bug`s carry one too) + one `who-acts` label + one `actor` label
  (agentic|human — D13, MANDATORY) + `parentId` of an epic unless the issue itself is the
  epic + a **self-assigned `assignee`** (`assignee: "me"`, MANDATORY — see below).
- **Component label is not optional and has no default.** Filing an issue with no landing leaf
  is a validation failure — the filer/executor rejects it rather than guessing. Pick the leaf
  from the issue's affected `apps/*`/`packages/*` paths (see `working-in-this-repo`).
- **Multi-component work → one component per label via the epic split (D9), never two leaves on
  one issue.** The landing group is single-select, so ≥2 components ⇒ an epic carrying each
  component leaf + one sub-issue per component, each with its single leaf.
- **Self-assign on creation (MANDATORY, except bugs).** Every issue and every epic is assigned
  to its creator at creation (`assignee: "me"`); nothing is filed unassigned — **except a
  `bug`-labeled issue, which is left unassigned.** Reassigning to another owner is a later,
  deliberate act.
- D9 still holds for cross-cutting work: ≥2 landings → one sub-issue per landing under the
  epic. Never one mega-ticket. Single-landing work is a leaf under an epic as well.
- D12 labels `blocked ⛔` and `needs-owner` are **not live** (reconciliation note above).
  Never add workflow states to the shared team. The no-epic stop uses Triage, not those
  labels.
- MCP quirks: `save_issue.labels` REPLACES the whole set — read current labels and resend
  the union. Relations (blockedBy/relatedTo) are append-only. Send raw markdown with real
  newlines. Bare `OME-N` identifiers auto-link and may create relations — wrap in
  backticks when no link is wanted.
- New app/package/workstream ⇒ its label created AND registered here in the same change.
- Every work item gets a mirror `docs/tasks/YYYY-MM-DD-<name>.md` at create; status closed
  in BOTH Linear and the mirror at finish. Linear is the status authority.
- A dev item descending from a product/marketing Asana task carries the Asana URL in its
  description (`asana_url` in the mirror frontmatter). Technical work NEVER goes to Asana
  (`asana-product` skill is read-only).
