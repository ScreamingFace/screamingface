# Verify Colab analytics recovery (OME-1768, PR #1703)

Local tests simulate browser failures. This smoke check verifies the actual Colab
browser bridge and production delivery without running a model or submitting a
leaderboard result. Existing browser declines and DO_NOT_TRACK remain respected.
Do not call `enable()` to prove automatic setup; explicit opt-in is a different test.

## Install the candidate

Run in a Colab cell, then restart the runtime before importing the SDK:

```python
%pip install -q --upgrade "screamingface @ git+https://github.com/ScreamingFace/screamingface.git@OME-1768-colab-recovery-tests#subdirectory=packages/screamingface"
```

The branch is a test candidate, not a released version. For reproducible results,
replace the branch name with the latest PR commit SHA. The development package's
version is not the published release number. To record the installed source:

```python
from importlib.metadata import distribution
print(distribution("screamingface").read_text("direct_url.json"))
```

## Normal client use

Run this cell three times. Invalid input intentionally raises TypeError before any
model request. Analytics still records the attempted operation. Setup may wait up
to five seconds; delivery continues in the background.

```python
import screamingface as sf

with sf.Client() as client:
    try:
        client.evaluate([])
    except TypeError:
        print("Expected validation failure; no model call made.")
print(sf.analytics.status())
```

After a few seconds, run `sf.analytics.status()` again. Expect `enabled=True`,
`pending=False`, and `last_error=None` when the browser is healthy and has not opted
out. If the first attempt fails, the next evaluation should recheck consent without
manual setup or enable calls. `setup_attempts` increments only for new attempts.
If it stays disabled, record `choice`, `last_error`, `last_error_stage`, and
`setup_attempts`; do not assume a timeout without that evidence.

In production PostHog project 601615, open Activity, use the last hour, and filter
`origin = colab`. Match `persistent_id` to the status output and the time to your
run. Each tracked attempt should have `evaluation_started` and
`evaluation_finished` with the same `operation_id`; the finish outcome is `failed`
because the input was intentionally invalid. Delivery can lose events; status is
not proof of receipt. The PostHog rows provide that proof.

## Recovery after one simulated failure (optional)

This uses private adapter APIs only to inject one browser failure. Run after the
normal check, with an accepted browser preference. It does not change that saved
preference or explicitly enable tracking:

```python
from screamingface._analytics import colab

original_exchange = colab.exchange

def fail_once(*args, **kwargs):
    colab.exchange = original_exchange
    raise TimeoutError("Simulated temporary browser failure")

colab.exchange = fail_once
try:
    colab.bridge().control("setup")
    colab.bridge().wait_for_setup()
finally:
    colab.exchange = original_exchange
print(sf.analytics.status())
```

Expect unknown/disabled with `last_error="setup_timeout"`. Run the normal client
cell again: a healthy browser should recover automatically and produce a new pair
of events. Nothing from the failed consent attempt is replayed.

## Opt-out control

Set `os.environ["DO_NOT_TRACK"] = "1"`, run the normal client cell, and confirm
`enabled=False` and no new events for that attempt. Wait for previous background
traffic before this check so it is not mistaken for new traffic. Remove only the
test value afterward if it was not present before testing. A saved decline should
also remain declined across evaluations and runtime restarts.
