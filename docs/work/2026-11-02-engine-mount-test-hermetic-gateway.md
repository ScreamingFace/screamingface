---
ticket: OME-1799
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# engine-mount-test-hermetic-gateway — keep the mount test off the developer's own gateway

## Intent

`test_a_direct_hit_on_a_benchmark_endpoint_gets_the_engines_404` built its local App without
naming a gateway, so the App fell back to the loopback default `127.0.0.1:9105`. On a laptop
whose own gateway lists a local model (`ollama/...`), the run behind `/corpus` admits that model,
builds its own world (by design: `shared_world_serves` in `runner/main.py`), and logs the
holdings-shelf line a second time. The test's count then reads 2, and the pre-push hook refuses
every Engine push from that laptop. CI never saw it: nothing listens on 9105 there.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_local_node_mount.py`: the one test names
  `aigateway_base_url="http://aigateway.test"` (the address its own `url4.toml` already uses).
- `.claude/test-change-approvals/OME-1799.json`: pins the edit to an existing test.

## Test plan

- Reproduce first: a stand-in gateway on 127.0.0.1:9105 listing `ollama/qwen3:8b` makes the test
  on `main` fail with `assert 2 == 1`.
- With the fix: the test file passes with that stand-in gateway up and with no gateway at all.

## Acceptance

- The mount test gives the same result whether or not a gateway runs on the developer's machine.

## Outcome

- **Actual files:** as planned, plus this ledger and the `docs/tasks` mirror.
- **Commits:** see the PR.
- **Gates:** `tests/unit/test_local_node_mount.py` 7 passed (stand-in gateway with an `ollama`
  model up; and with nothing on 9105). On `main` with the stand-in up: 1 failed (`2 == 1`).
  ruff check, ruff format and pyright clean on the touched test file.
- **Deviations:** none. A stand-in gateway listing only a hosted model did NOT reproduce the
  failure; the local-model listing is the trigger, and the code comment says so.
