# OME-950 — Implementation plan

- **Spec:** `docs/spec/2026-08-23-OME-950-relative-route-span-name.md`
- **Linear:** https://linear.app/openmined/issue/OME-950/report-relative-url4-routes-in-span-names
- **Branch:** `OME-950-relative-route-span-name`
- **Stack:** `url4` (`sdlc-python`)

## 1. RED — pin relative route identity

Add focused observation tests that execute a real `RelUrlNode` through `url4.dag.run` and require
its `NodeStarted.detail` to equal the static route. Cover both a successful fetch and an endpoint
failure so the route identity is independent of outcome and the existing start/finish bijection
stays intact.

Run the focused tests before changing production and confirm they fail because detail currently
falls back to an empty string.

## 2. GREEN — expose the existing path attribute

Add `path` to the existing ordered attribute selection in `url4.dag.executor._detail`. Do not add
a new model field, event, adapter, or special case for ScreamingFace.

Run the focused observation tests, then the complete URL4 test suite.

## 3. Verify and deliver

- Run `uv run .claude/scripts/run_gates.py url4` from the repository root.
- Review the diff for payload disclosure, public-wire blast radius, and accidental behavior change.
- Complete the ledger, commit with `Refs: OME-950`, push, and open a draft PR against `main`.
- Keep OME-934/932 and their PRs open as fallback until the span-based path is proven end to end.
