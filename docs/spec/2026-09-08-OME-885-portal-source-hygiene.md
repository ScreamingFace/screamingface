# OME-885 — Public portal source-hygiene contract

## Context

The Scoreboard mounts `apps/scoreboard/portal/` directly at `/`. Its HTML, JavaScript, CSS,
Markdown, and text files are therefore public responses rather than private source artifacts.
Current files expose ticket history, agent-only comment anchors, and internal repository paths.

## Decisions

1. **Clean the source.** Keep the portal dependency-free and do not add a minifier, bundler, or
   comment-stripping build step.
2. **Forbid internal markers in served text.** A served text response must not contain an
   `OME-<number>` reference, `AIDEV-NOTE`, `INVARIANT`, `.claude/`, or `worktrees/`.
3. **Test the public boundary.** The guard requests every file in the mounted tree through the
   application and scans responses with textual media types. Binary fonts and images are fetched
   but not decoded or scanned.
4. **Preserve useful rationale.** Short comments that explain current behavior may remain after
   being rewritten in public-safe terms. Internal history, deferred-work notes, and cross-ticket
   reasoning move to the work ledger.
5. **No product change.** Markup, styles, browser behavior, copy rendered to users, and public
   routing remain unchanged.

## Acceptance

- Every portal file remains reachable at the same path.
- No textual response from the mounted portal tree exposes a forbidden internal marker.
- Maintainer rationale removed from served files is recorded in the work ledger.
- No dependency or build step is introduced.
- Full Scoreboard gates pass.
