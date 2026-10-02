## Summary

<!-- What changed and why (1–3 sentences). -->

**Refs:** OME-N

## Components touched

<!-- e.g. apps/aigateway, apps/scoreboard, packages/<name> — this drives which CI runs and who reviews. -->

## Test plan

<!-- Checks are path-dependent. List what you actually ran. -->

- [ ] Ran the touched app's local gates (`uv run ruff check && uv run pyright && uv run pytest`)
- [ ] Gateway request/refresh change → ran the aigateway live tests locally
- [ ] Screenshots / recording attached (UI changes)

## Cross-service notes

<!-- If this spans another owner's area, state the contract and @-mention them. -->
