---
ticket: OME-1494
stack: screamingface
status: done
started: 2026-11-27
finished: 2026-11-27
---

# sdk-provenance-views — show each Benchmark's provenance and saturation in the SDK notebook views

## Intent

Since OME-1455 the SDK decodes `Benchmark.provenance` and `Benchmark.saturation` but no view shows them. The listing rows gain a saturation mark, the Benchmark card shows the block (authors, paper, harness, website, licence, Human Baseline, Frontier Score, content warning, notebook name), the per-origin link hardcode goes away, and `LeaderboardInfo` carries the block (decoded from the Scoreboard's own `provenance` and `saturation` keys) so the leaderboard view shows the same strip. The spec is the Linear issue; no new design.

## Planned changes

- `src/screamingface/_ui/cards.py` — saturation chip on rows, provenance items on the card, remove `_ORIGIN_SOURCES` links.
- `src/screamingface/leaderboard.py`, `src/screamingface/_scoreboard/leaderboards.py` — `LeaderboardInfo.provenance` / `.saturation`, decoded from the Scoreboard's nested block.
- `src/screamingface/_ui/leaderboard_view.py` — the strip above the rows.
- `tests/test_benchmark_views_provenance.py` (new); minimal edits to tests pinning the removed origin links; public-surface snapshot.

## Test plan

- Bare Benchmark (provenance None, saturation unknown): row and card carry no provenance markup (F1, F2).
- Full Benchmark: saturation chip, card items, leaderboard strip; absent field leaves no placeholder, never a dash.
- Unknown verdict word renders verbatim, unstyled.
- Non-http(s) link is not rendered as a link.
- LeaderboardInfo decodes the Scoreboard block; a Scoreboard without the keys decodes as today.
- Example notebooks regenerate byte-identical on a second run (F4).

## Acceptance

- See OME-1494.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `_ui/leaderboard_style.py` (one `.sf-lb__strip` rule) and `CHANGELOG.md` (the public-surface test requires it).
- **Commits:** see the PR.
- **Gates:** `run_gates.py screamingface`: ALL GATES GREEN (8667 tests, coverage 97.00%, notebooks check, build, distribution). Example notebooks rebuilt twice: byte-identical, no diff.
- **Deviations:** (1) The listing is chips per row, not columns: the Cases chip already existed, so only a `saturation: <word>` chip is added, shown for any verdict except `unknown` (a bare Benchmark must render as today). (2) Not done: grouping the listing by verdict order; the ticket does not say where. (3) The block has no dataset link, so the card shows paper, harness and website. (4) `_ORIGIN_SOURCES` links removed; the origin display names (`ScreamingFace`) stay in a names-only map so existing chips read the same. (5) `LeaderboardInfo` decodes the Scoreboard's own nested `provenance` and `saturation` (already served), which needed a small decoder in `_scoreboard/leaderboards.py`. (6) Edited seven assertions in two existing test files that pinned the removed links, plus the public-surface snapshot; approval manifest `.claude/test-change-approvals/OME-1494.json`.
