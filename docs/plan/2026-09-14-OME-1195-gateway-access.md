# OME-1195 — implementation plan

1. Add new route tests for the configured/missing context field, valid BYOK/hosted and profileless/no-auth access, selection errors, caller isolation and no dispatch/credential injection.
2. Confirm RED against the unchanged route.
3. Add the field after document composition, using the already resolved target and provider's profileless/no-auth declarations; do not change static parameter-contract composition.
4. Run targeted tests and the full `uv run .claude/scripts/run_gates.py aigateway` gates.
5. Record results and wisdom review; commit and open a Gateway-only draft PR. Keep Client OME-1042 open. Engine passthrough already exists, so planned OME-1196 is canceled.
