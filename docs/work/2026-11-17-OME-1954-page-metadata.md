---
ticket: OME-1954
stack: scoreboard
status: in_progress
started: 2026-11-17
finished:
---

# OME-1954 — Complete portal search metadata

## Intent

Keep the metadata improvements while removing blanket noindex from populated spec/data pages, as agreed in review. Qualify recipe copy for imported results.

## Planned changes

portal/index.html; portal/spec.html; portal/data.html; test_portal_page_metadata.py; original spec/plan/work records.

## Test plan

Parsed title/description/canonical agreement, bare and parameterized spec/data indexing, independent full scoreboard gates and combined browser compatibility with PR 1800.

## Acceptance

All reviewed defects addressed, required gates green, desktop/mobile previews inspected in both themes, and the existing PR updated as FilipBolt. No real subscription is sent.

## Authorization and approach

On 2026-11-17 the owner requested taking over PRs 1800 and 1801 and explicitly selected keeping both PRs and pushing the fixes as FilipBolt. The accepted review includes updating the obsolete redirect test and removing the noindex contract from the metadata tests. Kyle confirmed both indexing decisions in the PR discussion. These narrow test updates implement that authorized contract change; unrelated existing tests are preserved.

Start from current main and integrate the original PR with a merge, preserving its commit as an ancestor so the existing branch can be updated without force-pushing another author's history. Existing specs and plans are amended with the accepted review scope before implementation.

## Outcome

Implemented the accepted review scope and integrated current main without rewriting the original PR history.

- RED: regression coverage reproduced the original failures before the fixes.
- GREEN: `uv run .claude/scripts/run_gates.py scoreboard` passed: append-only guard, Ruff lint/format, Pyright, full pytest suite with the 80% coverage gate, and all configured Node portal tests.
- Combined preview with both PRs: visually inspected at 1440px and 390px in light and dark themes. No document overflow or JavaScript errors. Mixed community/imported results and an imported-only board render; the imported-only board is indexable and appears in the sitemap.
- Browser checks: legacy redirects retain tracking parameters; submission links open history; intercepted follow-board signup includes the correct board id, current page URL and UTM value. No live HubSpot submission was sent.
- Local preview: `http://127.0.0.1:9181/benchmarks/inspect-agieval_sat_en/` (local fixture data only).
- Hosted checks and review remain required before merge. This takeover does not merge the PR.
