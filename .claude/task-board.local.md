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
labels:  # RECONCILED 2026-07-15 (OME-443) vs live Linear (list_issue_labels). See reconciliation note at bottom.
  # Product/landing axis — live Linear groups product areas under parent labels (app/pkg/research/extra).
  # There is NO live "Epic" workstream group anymore; the product area IS the app/* (or research/*) landing label.
  landing:
    "analytics": "ff4eeff4-5bca-48c7-bd7c-28702e39855a"  # owner-created, verified via Linear MCP 2026-09-09
    "aigateway": "f92de050-b7ec-41fe-a14a-d30c0d0be267"              # parent: app
    "aigateway/deployment": "874aa881-360e-4362-b80a-39c2ae823d97"  # parent: app
    "scoreboard": "3f8aa7fc-e9a0-461f-8a6b-0bf2dd7cf4d9"            # parent: app
    # RECONCILED 2026-08-18 (OME-876) against live Linear via `linear label list --all`:
    # this ID's label was RENAMED in Linear from "url4-engine" to "url4-sdk". Same label, new name.
    "url4-sdk": "b9bdd9c0-b03b-47e0-86c9-b3f45305212a"             # parent: app — url4 grammar/parser/DAG exec
    # The Engine app (apps/screamingface-engine). This is the label to APPLY for that app's work;
    # live issues already carry it (e.g. OME-676, OME-304).
    "screamingface-engine": "cc1ac9b3-45af-4bec-a112-560ad1f52680"  # parent: app — the ScreamingFace Engine
    # LEGACY, retained: the Engine app's previous name. Still exists in Linear and still applied to
    # issues filed before the rename, so it must stay resolvable for reading history. Do NOT apply
    # it to new work — the landing group is single-select, so it would collide.
    "url4-cloud": "295a9fe1-826e-49f8-8f11-e4f438aa27a1"           # parent: app — legacy (pre-OME-876)
    "desktop": "cef9d753-9675-4f7d-8ae7-afc7af802887"              # parent: app
    "desktop/benchmarks": "53bb9d19-95a2-4479-9acd-6ea6423ae251"    # parent: app
    "desktop/ensemble": "d55512f6-389d-4fc4-877a-6a6be434c4c1"      # parent: app
    "desktop/eval-runner": "543fbbde-bdd5-430b-8ecd-26f33628bdc3"   # parent: app
    "desktop/results-runs": "d0e1871e-db73-4ba6-bc7a-fcbfde515e40"  # parent: app
    "py-screamingface": "8d3dd8bd-5365-4ab7-90d5-9e5317cf3157"      # parent: pkg
    "url4-python-sdk": "05d3d132-d508-4540-be46-4d10303e117a"       # parent: pkg
    "multi-turn": "b6926d8f-8693-45a1-bf08-0847bc516e04"            # parent: research
    "sota": "fad181c4-2834-47e1-9d4d-5b36c9000a49"                  # parent: research
    "repo-dev-processes": "220d479a-98b5-4b94-95ee-92635db5f0ae"    # parent: extra
    "auth+subsidies": "8c34e37b-f78f-4983-ae62-8f97ba26c28f"        # parent: extra
    "repo": "89353e43-30b4-4e4b-b0a6-d781f9dcfebc"                  # ungrouped (process; coexists with repo-dev-processes)
    "pkg/url4-python-sdk": "65e0b370-12c8-45e4-9b9d-0fb5fe72bac8"   # ungrouped (coexists with url4-python-sdk under pkg)
    "syft-space": "55b0b894-9717-4a82-9e40-aba3d01922cd"           # ungrouped
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
  # ── Reconciliation note (2026-07-15, OME-443) ─────────────────────────────────────────────
  # Labels present in the PRIOR card but ABSENT from live Linear (verified via list_issue_labels):
  #   - epic_group workstreams (url4 Engine, AI Gateway, Eval Runner & Datasets, Results & Runs,
  #     Leaderboard, Auth & Subsidized Compute, Desktop App, Python SDK, Multi-turn Ensembles,
  #     SOTA Hunt, Compute Budgeting): the "Epic"/workstream axis no longer exists; product area
  #     folded into the app/* + research/* landing labels above.
  #   - type_ish Bug / Feature / Improvement: replaced by type decision / task.
  #   - STOP labels "blocked ⛔" and "needs-owner": DO NOT EXIST. The D12 STOP mechanism below is
  #     currently unbacked. OWNER ACTION: recreate these two labels in the Linear UI, or switch the
  #     D12 rule to another signal. Until then, record a STOP as a `design-session`/`deferred`
  #     label + a comment stating the exact question.
  #   - landing app/aigateway, app/scoreboard IDs were stale; live labels are aigateway / scoreboard
  #     (parent "app"). repo and pkg/url4-python-sdk IDs were correct and are retained.
  # who_acts/actor `group:` parent IDs from the prior card were dropped (unverified + unused for
  # filing, which resolves by member label). Re-add if a group-level operation ever needs them.
priority: { P1: 2, P2: 3, P3: 4 }  # Linear ints; 1 (Urgent) reserved for incidents
close_template: |
  Commits: <sha> <message>[, …]
  Gates: <run_gates.py summary / test counts>
  Ledger: docs/work/<file>.md
  Deviations: <none | list>
  Owner-verify: <none | what to check visually>
---

# Ticket rules (bind alongside the task-management skill)

- Every work item: team Engineering + project 😱 ScreamingFace V1 (D11) + a landing label
  (`app/*`/`pkg/*`, or `repo` for process work) + one `who-acts` label + one `actor` label
  (agentic|human — D13, MANDATORY). Add the workstream (`Epic` group) label whenever the
  work belongs to one; workstream additions are coordinated with the project lead.
- D9: ≥2 `app/*`/`pkg/*` labels → cross-cutting: epic carrying the workstream label + all
  affected landing labels, with one sub-issue per affected app/package (one SDLC unit
  each). Never a single-app filing, never one mega-ticket.
- D12 STOPs: apply `blocked ⛔` or `needs-owner` + a comment stating the exact question;
  the issue stays In Progress; remove the label when resolved. Never add workflow states
  to the shared team.
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
