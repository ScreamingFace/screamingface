---
ticket: OME-1309
stack: scoreboard
status: done
started: 2026-11-10
finished: 2026-11-10
---

# External result edit history

## Intent

Preserve previous external-result values when edited. Owner requested implementation and clarification of unclear choices. Work is authorized under E20; Linear writes still require separate approval.

## Current behavior

BaselineStore.import_baseline upserts one current observation keyed by benchmark/model/source, then stamps last_imported_at inside the same transaction. Previous observations are lost. attached_by is internal; other observation fields are already public even on private boards. Comparison eligibility is derived on reads and must never be inherited from an earlier version.

## Decisions

Owner chose A/A: preserve changed manual/import observations and expose previous values through an Updated link. Identical imports only refresh last_imported_at. Attribution stays internal. Implement a separate history page to keep the ranked table compact.

## Planned changes

After owner answers, write the spec and implementation plan, add a version model and migration, preserve old observation and update current state atomically, then add the selected read/UI surface. Initial imports must not appear as edits; legacy rows must not gain fabricated historical dates. Preserve stable row identity and current-ranking behavior.

## Test plan

Test changed vs identical imports, metadata-only edits and clearing optional fields, legacy first edit, multiple changes in one batch, complete rollback on error, concurrent first/existing-row imports on PostgreSQL, migration of populated databases, private attribution exclusion, and bounded history reads if exposed. Preserve existing timestamp/concurrency regression tests. Preview any UI changes locally at desktop/mobile sizes in both themes before a PR update.

## Acceptance

Old values remain recoverable; a failed import cannot leave partial history or current state. Only the current eligible observation affects ranks. Public visibility follows the owner's choice. Full gates pass; migration ships with model.

## Outcome

Implemented owner-approved A/A: immutable changed-observation snapshots, no-op refreshes, explicit public history DTOs with bounded cursor pages, Updated links and a dedicated history page. Attribution stays in private storage. Initial imports do not appear as updates. Legacy state is retained before its first edit with an unknown date.

Migration 0023 adds the version table and two current-row fields. A populated-database test exposed the need for db_default=0, which was fixed before shipping. PostgreSQL races cover absent, legacy and already-versioned rows, including identical concurrent observations. The unchanged timestamp race tests also pass. JSON type changes are retained, while key reordering is ignored.

Validation: 53 focused PostgreSQL/migration/regression tests passed; 21 focused portal tests passed; full scoreboard gates passed with the documented append-only exception, plus repository gates. Presentation assertions were changed for the approved Source button/shared notes, and the published-field allowlist was extended for the two history fields; ranking, source-safety and attribution assertions remain. Frontend and backend RED failures were observed before implementation.

Browser: inspected desktop 1440px and mobile 390px in light/dark; no page overflow. Clicked Updated from a mixed board, used the theme switch, and opened the real external Source with the keyboard. No browser errors; only expected localhost analytics warnings. Local preview history values are synthetic and are not evidence of publisher corrections. Screenshots remain ignored local artifacts.

Wisdom review: only the scoreboard is touched; the new schema ships with its migration; no new dependency or public edit API. All snapshots and current writes share one transaction/row lock. Existing profile eligibility and ranking behavior stay unchanged. The read API explicitly excludes private attribution. Import jobs must use the new image after rollout; old overwritten values cannot be recovered.

No live import, production change or Linear write. The SAD profile remains a separate draft PR (#1729), and live acceptance still awaits verified firecall access and profile deployment.

Correction (2026-11-12): the later layout commit changed existing JavaScript presentation assertions, so the earlier claim that its original bytes remained a prefix was false. Initial validation bypassed the append-only precheck. The review follow-up records exact base/approved blobs for both affected test files in `.claude/test-change-approvals/OME-1309.json`, enables the same exact approval check for JavaScript, and reruns full gates without `--skip-append-only`.
