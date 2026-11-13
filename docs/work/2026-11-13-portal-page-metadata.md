---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: scoreboard
status: done
started: 2026-11-13
finished: 2026-11-13
---

# portal-page-metadata — search metadata on the home, about, spec and data pages

## Intent

The home page is the landing for broad searches, but its title (`screamingface · benchmark
receipts`) and description contain none of "leaderboard", "fusion", "ensemble" or "router". No
portal page declares a canonical address, and `/` and `/index.html` both answer 200. The spec
and data pages show nothing without their query parameters and are indexable as near-empty
documents. This unit states what the home page is in its head, gives home and about a
canonical, and keeps the two parameter pages out of the index.

Spec: `docs/spec/2026-11-13-portal-page-metadata-spec.md`. Plan: `docs/plan/2026-11-13-portal-page-metadata.md`.

## Planned changes

- `apps/scoreboard/portal/index.html`: title, description, matching `og:`/`twitter:` text,
  canonical.
- `apps/scoreboard/portal/about.html`: canonical.
- `apps/scoreboard/portal/spec.html`, `data.html`: `robots: noindex,follow`.
- `apps/scoreboard/tests/unit/test_portal_page_metadata.py` (new).

No Python source, model or schema change.

## Test plan

- Home title and description name a leaderboard and fusions; `og:` and `twitter:` text match.
- Home and about each declare one canonical, equal to their `og:url`.
- Spec and data carry `noindex,follow`; home, about and the board shell do not.
- No existing test is edited.

## Acceptance

- `curl` of `/` shows the new title, description and canonical.
- `uv run .claude/scripts/run_gates.py scoreboard` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see PR.
- **Gates:** `run_gates.py scoreboard` → ALL GATES GREEN (append-only check, ruff, format,
  pyright, pytest with coverage, node portal tests).
- **Deviations:** none. No existing test edited.
- **Not verified:** how the new home title and description read in a live search result; the
  wording is a proposal for the owners of the home page copy.
