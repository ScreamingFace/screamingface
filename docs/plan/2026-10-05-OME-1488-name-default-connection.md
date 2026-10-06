# OME-1488 — plan

Spec: `docs/spec/2026-10-05-OME-1488-name-default-connection.md`. Branch
`OME-1488-name-default-connection` from `origin/main` at `e9e850e8`.

1. **RED.** `tests/unit/test_server_connections.py` with the two-connection config; confirm the
   `ParamsError` the dev pod logged. Add the AST guard; confirm it lists the 8 calls.
2. **GREEN.** `DEFAULT_CONNECTION` in `db.py`; name it at the 8 calls.
3. **Mutation.** Remove the name from `read_snapshot` only; the behaviour test and the guard fail.
4. **Gates** `run_gates.py scoreboard --base origin/main`, ledger outcome, mirror, PR `Refs: OME-1488`.
