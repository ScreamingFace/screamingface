# DNS timeout correction

1. Add a regression that measures asyncio.run completion with a stalled resolver, and see it fail on the current code.
2. Add the isolated system resolver and tests for success, errors, literal addresses, and cancellation cleanup.
3. Run focused tests and scoreboard gates; document the change, commit, and update #1749 as FilipBolt.
