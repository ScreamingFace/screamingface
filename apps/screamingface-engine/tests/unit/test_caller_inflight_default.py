"""The per-caller in-flight cap defaults to 24 (OME-1314).

FEATURE: one caller may hold 24 admitted runs at once, up from 8. The Client sizes its fan-out
from the enforced value (`GET /v1/limits`), so the default is the single number both sides
read.

WHY these three tests: the code default, the settings default and the env override are three
separate places that can drift. Pinning each one keeps the owner's 24 from silently reverting
to 8 through a second definition, and keeps the env var as the operator's override.
"""

from screamingface_engine import runner_queue
from screamingface_engine.config import Settings


def test_the_code_default_is_24() -> None:
    assert runner_queue.DEFAULT_CALLER_INFLIGHT_CAP == 24


def test_settings_default_is_24(monkeypatch) -> None:
    monkeypatch.delenv("URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP", raising=False)
    assert Settings().run_queue_caller_inflight_cap == 24


def test_the_env_var_still_overrides_it(monkeypatch) -> None:
    monkeypatch.setenv("URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP", "7")
    assert Settings().run_queue_caller_inflight_cap == 7
