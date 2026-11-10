---
ticket: OME-1841
stack: scoreboard
status: in_progress
started: 2026-11-10
finished:
---

# OME-1841 — Homepage readability and keyboard access

## Intent

Implement the before/after preview approved by the owner on 2026-11-10. Improve
homepage readability, focus, touch targets, theme defaults and accessible navigation.

## Planned changes

- Portal CSS and homepage landmarks, skip link and paging announcement.
- Shared early theme initialization on all five portal pages; keep brand files unchanged.
- Focused regression coverage and explicit CI/card test registration.
- Spec, plan and existing-ticket mirror.

## Test plan

- RED: OS theme fallback, stored choice precedence, denied storage; paging announcements.
- Structural HTML assertions for landmarks and shared initialization.
- Browser checks at 1440/375 in both themes: contrast, focus, hit areas, wrapping,
  paging, search/filter, skip link and theme persistence.
- Full scoreboard gates and mirror check.

## Acceptance

Approved appearance; readable captions and visible consistent focus; 44px chrome
controls; system theme unless chosen; meaningful paging count. Gold-token correction
remains upstream. No API change or new dependency.

## Outcome

- **Actual files:** portal CSS, index semantics, shared theme-init.js and five entry
  points, catalog count handler; new theme/count/HTML tests, CI/card registration,
  banner-order assertion and byte-pinned approval, spec/plan/mirror.
- **Commits:** implementation commit on OME-1841-homepage-accessibility (see git log).
- **Gates:** full scoreboard run_gates.py passed, including lint, format, pyright,
  Python suite/coverage and every registered Node suite; mirror and diff checks passed.
- **Browser:** Chrome 1440×1000 and 375×1000, both themes; contrast, focus, target
  sizes, no overflow, skip navigation, paging/filter/search persistence, OS theme,
  stored choice and denied storage passed. Top and catalogue screenshots inspected.
- **Measurements:** captions/fine print/chart ticks/loading 5.99:1 light, 12.50:1
  dark. Ink focus 10.85:1 light, 15.91:1 dark. Chrome targets at least 44px; mobile
  grant link 51.875px tall. Display 38px, card titles 20px, desktop lead 20px;
  mobile lead retains the existing 16px body token.
- **Deviations:** first skip link supersedes the old banner-first DOM assertion;
  exact test change recorded in .claude/test-change-approvals/OME-1841.json.
  Footer moved outside main so it exposes a page-level landmark. Shared early
  script replaces duplicated inline bootstrap; vendored theme.js is unchanged.
- **Wisdom/review:** one small shared initialization path, no dependency or API
  change. Gold-token contrast remains upstream. No claim of full-page WCAG
  conformance or manual screen-reader testing. Awaiting PR review and deployment.
