# OME-1382 board half — plan

Spec: `docs/spec/2026-10-02-OME-1382-rank-on-reproduction-cost.md`. Branch
`OME-1382-rank-on-reproduction-cost` from `origin/main` at `edbecb66`.

1. **RED, pure.** `tests/unit/scores/test_reproduction_cost.py` against a `reproduction_cost`
   that does not exist yet.
2. **RED, routes.** `tests/unit/test_reproduction_cost_routes.py`: seed rows through the store,
   assert on `/v1/leaderboard/{id}` (cost and `on_pareto_frontier`), `/frontier` (card and trend),
   the spec history route, and `format_jsonl_bytes` before and after.
3. **GREEN.** The module; select the two extra columns in both raw queries and convert them in
   `_to_python_rows` (`cache_saved_cost_usd` nullable); serve the rule at the five paths.
4. **Mutations:** remove the status gate; remove the sum at the Pareto input only; route the sum
   through `_score_to_schema` (the export test must catch it).
5. **Gates** `run_gates.py scoreboard --base origin/main`, ledger outcome, mirror, PR.
