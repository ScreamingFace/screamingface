# Analytics service

Use repository task-management and sdlc-python skills. Spec/plan: OME-1152.
Core contract/ingestion/ports never import adapters. No ORM or durable queue.
Tests use synthetic events and a mock upstream; never production PostHog credentials.
Four event names and strict fields only. No identity association, SDK instrumentation,
raw request logging or IP/header enrichment.
Bridge consent/cookie endpoints are governed by the approved
`docs/spec/2026-09-25-analytics-colab-bridge-spec.md`; enabled only by explicit configuration.
Run gates from repository root: `uv run .claude/scripts/run_gates.py analytics`.
