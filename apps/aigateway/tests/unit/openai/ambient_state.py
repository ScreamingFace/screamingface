"""The hand-written ambient-LiteLLM inventory the direct-OpenAI suites neutralize.

WHY this is a shared module rather than a fixture inside one suite: three cohesive
suites need the SAME neutralization. The projection and keyed-parameter suites need it
so their key and participation assertions measure the request rather than whatever
``litellm`` was left holding; the runtime-guard suites need it because ambient state IS
their subject. ``litellm`` is imported once per session and pytest does not reset module
globals between tests, so an earlier test — or litellm's own import-time wiring — can
leave a callback list or a rules list populated for everything that follows.

AIDEV-NOTE: ``AMBIENT_SAFE_STATE`` is written out BY HAND and is deliberately NOT derived
from ``_LITELLM_GLOBAL_TRUTHY_FIELDS`` / ``_LITELLM_GLOBAL_CALLBACK_FIELDS``. That
independence is the whole point: if the setup were generated from the production tuples,
a field the GUARD forgot would also be a field the SETUP forgot, and the pair would keep
passing together while a real ambient hazard leaked into every test. That is precisely how
``modify_params`` stayed invisible for a full review cycle.
``test_openai_runtime_guard.py`` ties the two sides back together in BOTH directions, so
neither list can drift from the other in silence.
"""

from __future__ import annotations

from typing import Any

import litellm
import pytest

AMBIENT_SAFE_STATE: dict[str, Any] = {
    "secret_manager_client": None,
    "model_alias_map": {},
    "proxy_auth": None,
    "model_fallbacks": None,
    "headers": None,
    "pre_call_rules": [],
    "post_call_rules": [],
    "drop_params": False,
    # OME-884 review cycle 2: the ambient MUTATOR. While it was absent from this helper,
    # LiteLLM's session default leaked into every participation assertion.
    "modify_params": False,
    "callbacks": [],
    "input_callback": [],
    "success_callback": [],
    "failure_callback": [],
    "_async_input_callback": [],
    "_async_success_callback": [],
    "_async_failure_callback": [],
}

# The two ambient reads that live in the ENVIRONMENT rather than on the module, so they
# are cleared rather than set. Kept beside the inventory because the guard treats all
# three sources as one verdict.
AMBIENT_SAFE_ENV: tuple[str, ...] = (
    "OPENAI_CUSTOM_HEADERS",
    "EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER",
)


def safe_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize every ambient global this provider fails closed on."""
    for name in AMBIENT_SAFE_ENV:
        monkeypatch.delenv(name, raising=False)
    for field, safe_value in AMBIENT_SAFE_STATE.items():
        monkeypatch.setattr(litellm, field, safe_value)
