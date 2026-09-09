# Analytics service

Use repository task-management and sdlc-python skills. Spec/plan: OME-1152.
Core contract/ingestion/ports never import adapters. No ORM or durable queue.
Tests use synthetic events and a mock upstream; never production PostHog credentials.
Four event names and strict fields only. No identity association, SDK instrumentation,
consent/cookie endpoints, raw request logging or IP/header enrichment.
Run gates from repository root: `uv run .claude/scripts/run_gates.py analytics`.
