# OME-1336 — User-request intake bot

Status: in progress · Stack: repo (process/automation) · Runtime: scheduled claude.ai routine

## Problem

Users and prospects tell us what they need on recorded calls and in Slack, but turning that into
tracked work is manual and lossy — a request mentioned on a call or dropped in a channel often
never reaches the backlog, or gets re-filed as a duplicate. We want a daily autonomous agent that
harvests those requests from both sources, normalizes each into a fixed template, and files it as
a Linear ticket for triage — without duplicating what is already tracked.

## Sources

### S1 — Calls: `OpenMined/screamingface-calls` (private)

Layout: `calls/<YYYY-MM-DD> <person-slug> (<om-owner>)/{notes.md, transcript.md}`.

- `notes.md` frontmatter is structured and authoritative for identity:
  `researcher` (contact full name), `caller` (OM owner email), `attendees` (emails — the
  non-`@openmined.org` one is the contact; its domain gives the org), and, when the call is linked
  in HubSpot, `hubspot_contact_id` / `hubspot_deal_id` / `hubspot_card` (a ready URL). The notes
  body has a short summary, per-topic bullet sections, and a `Next steps` checklist.
- `transcript.md` (present on newer calls) holds timestamped verbatim dialogue — the source of the
  **exact quote**. Older calls have only `notes.md`; then the quote falls back to the most on-point
  notes bullet, marked `(paraphrased from notes)`.

Access: `gh api repos/OpenMined/screamingface-calls/...` (private, already reachable) or the GitHub
MCP. URL-encode the space-bearing folder paths.

### S2 — Slack allowlist

`#scream-q3-get-100-mau-in-sept` and `#scream-updates` (config — more channels may be added). These
are **activity/update** channels: most messages are status updates, not user requests, so the
signal filter (D5) is strict here. A message counts only when it relays a concrete request or
interaction from a named external user. Identity comes from the Slack profile and, best-effort,
a HubSpot lookup by name/company.

## Decisions

### D1 — Execution model: a scheduled claude.ai routine, not a deployed service

Filing to Linear must go through the Linear MCP (repo law: "Linear via MCP only; API tokens / raw
GraphQL forbidden"), and extraction is LLM-shaped work. So the bot is an **autonomous Claude agent**
run daily as a claude.ai routine (`RemoteTrigger`), which fires server-side independent of any local
session. Not a new `apps/*` service. `CronCreate` is rejected for production use: it is session-only
and auto-expires after 7 days. The canonical prompt lives in the repo (D8) so it is reviewable and
versioned; the routine runs a copy of it.

### D2 — One request → one regular Triage ticket

Every distinct request becomes a **regular issue** (not an epic) created directly in the **Triage**
state, in team `Engineering` / project `😱 ScreamingFace V1`, carrying the `user-request` label
(id `795f5422-d364-4e0c-8f9a-583672d0e4df`, already present). A best-guess landing leaf may be added
when obvious; otherwise leave landing for a human triager. Triage is the human safety net that makes
daily auto-filing (D6) safe.

### D3 — Every ticket is parented under a matching epic + the epic gets a demand comment

Each filed ticket is **parented under the best-fit existing epic** (`parentId`) — the project keeps a
rich epic taxonomy (E1–E21 etc.; `list_issues {label: "product-feature"}` returns the current set,
all titled `… [EPIC]`). Then **add or update a demand-summary comment on that epic** (D10) so the
repeated find is visible in one place.

- **No fitting epic → do NOT auto-create one** (epic creation is an owner action). File the ticket in
  Triage **unparented**, and in the run log **propose** a new epic (name + rationale) for the owner;
  on owner consent, create it in Triage tagging **@Irina Bejan @Kevin McDonough** for scope approval,
  then parent the ticket under it. Never file silently-orphaned tickets without flagging.
- When the mapping is genuinely ambiguous between two epics, pick the nearest and say so in the epic
  comment ("tentative fit — reassign if a better home exists").

### D10 — Epic demand-summary comment (the "repeated find" rollup)

For each epic that receives ticket(s) in a run, post one comment (or append to the existing intake
comment) titled **"User-request intake (OME-1336) — repeated demand under this epic"** listing every
child request: `OME-N · Requester (org) — one-line ask` + a short quote. This turns each epic into a
live demand signal (how many users asked, who, in their words). On later runs, update the same rollup
rather than posting a fresh comment each day.

### D4 — Always assign + subscribe Irina

Set `assignee: irina@openmined.org` and add her as a subscriber, and end the body with a
`cc @Irina — please review.` line, so every filed request lands in her review queue.

### D5 — Signal filter (what to file)

File only a concrete, actionable **user-reported feature, interaction, or concern**. A request
qualifies when it has (a) an identifiable external requester and (b) a specific ask or friction
point. Exclude internal team chatter, status updates, scheduling logistics, and pure praise with no
ask. When in doubt on a Slack message, do **not** file (calls are higher-signal and may be filed
more liberally). Prefer one ticket per distinct ask; a single call raising two unrelated asks → two
tickets.

**Attribution matters (calls).** On a sales/research call the OpenMined rep often *pitches* a
feature; the user reacting to it is not the same as the user *asking* for it. File only when the ask
originates from — or is explicitly endorsed/needed by — the **external user**. Capture the quote from
the user's turn, not the rep's. If the user only reacts mildly to a rep's pitch, treat it as
low-confidence and skip (or note it on an existing ticket rather than filing new). Example from the
dry run: Amy Rouillard's need for private benchmarks over a South-African healthcare cohort is
user-driven (file it); the shared-cache idea in the same call slate was pitched by the rep and only
endorsed by the user (weaker — do not file as that user's request).

### D6 — Cadence: daily, auto-file

Runs once daily (off-peak minute, e.g. `17 8 * * *` local). It files automatically — no
propose-then-confirm step — because everything lands in Triage assigned to Irina for review.

### D7 — Deduplication (windowed + fingerprint + semantic)

No external datastore. Three layers:
1. **Window** — consider only call folders dated ≥ (today − 3 days) and Slack messages from the last
   ~26h. (3-day call window absorbs the notes/transcript sync lag in the calls repo.)
2. **Fingerprint** — embed a machine-readable marker in every filed ticket body:
   `<!-- source-fingerprint: <id> -->` where `<id>` is `calls/<folder path>` for a call or
   `slack:<channel-id>:<message-ts>` for Slack. Before filing, `list_issues {label: "user-request",
   updatedAt: -P30D}` and skip any candidate whose fingerprint already appears. One fingerprint per
   source item; a call raising two asks uses `#ask1` / `#ask2` suffixes so both can be filed and
   both dedup.
3. **Semantic guard** — if a candidate restates scope already captured by an open `user-request`
   ticket from a *different* source, append a short comment to that ticket (with the new
   fingerprint) instead of filing a duplicate.

### D8 — Canonical prompt versioned in-repo

The runnable instructions live at `.claude/agents/user-request-intake.md` and are the single source
of truth for the routine's behaviour. The routine's stored prompt is a copy; changes are made in the
repo file first, then re-synced into the routine (`RemoteTrigger update`).

### D9 — Repo mirror for filed tickets is deferred

The bot writes only the Linear ticket. The `docs/tasks/` mirror + `docs/work/` ledger that the SDLC
normally requires are created by a human when the ticket is **promoted out of Triage** into real
work — this avoids daily PR churn from raw, unreviewed intake.

### D11 — Weekly digest report

Once a week (Friday run), over a rolling 7-day window, the bot produces/refreshes a team-facing digest —
**"What users requested this week"** — grouped by theme and tiered by the **Linear priority of the roadmap
epic** each request maps to (Urgent → High → Medium), plus an **Out of scope** section (black-box-thesis
conflicts / unplanned niche asks) and a full appendix table (ticket · requester · org · ask · epic). It is a
Claude doc (the **Claude-Docs** connector is available to the routine); the bot **reuses/refreshes the same
doc** each week rather than spawning a new one, and shares the link on `OME-1336` and in `#scream-updates`.
Priorities are pulled fresh via `list_issues {label: "product-feature"}`.

## Ticket template (body the bot writes)

```
**Source:** <call | slack> · <call folder path OR channel #name + message permalink> · <YYYY-MM-DD>
**Requester:** <full name> · <org / site> · <email>
**HubSpot:** <hubspot_card URL | "not linked">
**Features requested:**
- <feature 1>
- <feature 2>
**Verbatim excerpt (capture generously — more transcript beats a snippet):**
> <the requester's full turn(s) + enough surrounding exchange to make the ask self-contained — several sentences, with transcript timestamp(s). Mark "(paraphrased from notes)" only if there is no transcript.>

<!-- source-fingerprint: <calls/<path> | slack:<channel-id>:<ts>> -->
cc @Irina — please review.
```

- Title: an imperative summary of the ask (no issue-ID prefix, no requester name dump), e.g.
  "Add bring-your-own-model support for on-prem deployments".
- Labels: `user-request` (+ optional obvious landing leaf).
- State: Triage. Assignee + subscriber: Irina. Parent: existing epic when unambiguous (D3).

## Extraction rules

- **Calls:** read `notes.md` frontmatter for `researcher`/`caller`/`attendees`/`hubspot_card`; derive
  org from the external attendee's email domain when HubSpot org is absent; mine the summary bullets
  + `Next steps` for the requested features; pull a **generous verbatim excerpt** from the matching
  `transcript.md` passage — the requester's full turn(s) plus enough of the surrounding exchange that
  the ask stands on its own (err toward more, several sentences, keep the timestamp). Fallback: the
  best notes bullet(s), flagged paraphrased.
- **Slack:** resolve author via `slack_read_user_profile`; read the full thread with
  `slack_read_thread` for context; best-effort HubSpot match via `search_crm_objects`; capture the
  **full message and relevant thread reply/replies verbatim**, not a fragment.

## Config (kept at the top of the runnable prompt)

- Calls repo: `OpenMined/screamingface-calls`, path `calls/`.
- Slack channels: `#scream-q3-get-100-mau-in-sept`, `#scream-updates`.
- Linear: team `Engineering`, project `😱 ScreamingFace V1` (slug `screamingface-v1-27666092fc7f`),
  state Triage, label `user-request`, assignee `irina@openmined.org`.
- Windows: calls ≥ today−3d; Slack last 26h. Dedup lookback: `user-request` issues updated in 30d.
- Weekly digest: Friday, rolling 7-day window (D11).

## MCP surface used

Linear MCP (`list_issues`, `get_issue`, `save_issue`, `save_comment`) — never raw GraphQL. Slack MCP
(`slack_read_channel`, `slack_read_thread`, `slack_read_user_profile`, `slack_search_*`). GitHub for
the calls repo (`gh api .../contents` or GitHub MCP). HubSpot MCP (`search_crm_objects`) for
Slack-side enrichment only — calls already carry HubSpot IDs. Claude Docs (Claude-Docs connector) for
the weekly digest (D11).

## Open risk — remote MCP-connector availability

claude.ai routines run headless; interactively-authenticated connectors can be disabled when an API
key is set in that context. Before relying on the schedule, fire the routine on demand
(`RemoteTrigger run`) and confirm Slack / Linear / HubSpot / GitHub are all reachable. If a connector
is unavailable remotely, fall back to a durable local `CronCreate` (`durable: true`, re-armed within
the 7-day window) or a thin `gh workflow` that invokes headless Claude with the needed tokens.

## Verification

1. **Dry run (calls):** run the prompt in "propose only" mode over 2–3 recent call folders
   (e.g. `evan-chen`, `tomer-galanti`); check the fields, quote fidelity, and epic mapping — no filing.
2. **Dedup:** re-run over the same folders → nothing filed (fingerprints already present).
3. **One live file:** let it file a single call → verify Triage state, `user-request` label,
   assignee + subscriber Irina, fingerprint marker present, epic parent when applicable.
4. **Slack path:** run over one allowlisted channel-day → author/org resolved; non-requests ignored.
5. **Schedule:** create the routine; `RemoteTrigger run` once and confirm remote connector access (risk above).
