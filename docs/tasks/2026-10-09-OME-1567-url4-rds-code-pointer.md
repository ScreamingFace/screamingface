---
id: OME-1567
linear_url: https://linear.app/openmined/issue/OME-1567/run-uri-intents-as-code-pointer-calls-in-url4-20
status: In Progress
type: Feature
priority: P1
labels: [url4-engine, agentic, autonomous]
created: 2026-10-09
closed:
---

# OME-1567 — Run URI intents as code-pointer calls in url4 2.0

Parent: OME-1289 (E4a). Sibling: OME-1568 (Engine).

A relative-URI or `url4://` intent runs as one code-pointer (RDS) call with the group's sources as
a JSON input document. Endpoints opt in with `rds=True`. Breaking change; joins url4 2.0.0 (release
PR #852 merges after this PR).

Spec: ../spec/2026-10-09-url4-rds-code-pointer/
Plan: ../plan/2026-10-09-url4-rds-code-pointer.md
Ledger: ../work/2026-10-09-url4-rds-code-pointer.md
