"""The pure capture key of one chat call (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - a traced call is captured under the SAME key hash that the live global
cache uses for the same body, so a later replay can find the call again by that hash.

INVARIANT: PURE and TOTAL. No I/O; it reads no account, profile or credential; it never raises.

WHY it reuses ``build_global_cache_plan``: every eligibility gate of the live cache applies
unchanged, but the operator switch and the caller opt-out are ignored on purpose
(``participate=True``, ``cache_enabled=True``). An opted-out call (``use-cache: false``) must still
have a key, because CV-H1 keeps its prompt in ``request_cache_prompt``, and capture must work when
the live cache is off (local mode).

AIDEV-NOTE (exception to a documented rule): the docstrings of ``canonical_key_material``
(``request_cache/global_keys.py``) and ``canonical_material`` (``request_cache/canonical.py``) say
the material is "never persisted". E14 persists this material in ``request_cache_prompt`` on
purpose (``erd.md`` 3.1). Those two files are NOT edited. The material is stored, never logged.

Consequence: a provider without a global-cache projection (the base default is ``CacheBypass``:
gemini, codex, antigravity, ollama today), a streaming body (``BYPASS_STREAM``) and every other
unkeyable body get NO capture key. Such a call still gets a capture row with ``key_hash = NULL``,
and GW-freeze counts it as missing (plan OD-2, spec gap SG-1).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Final

from ..cache_ports import CacheBypass
from ..plugin_base import ProviderPluginBase
from ..request_cache.global_controls import GlobalCacheControls
from ..request_cache.global_keys import (
    GlobalCacheKeyResult,
    build_global_cache_key_dto,
    canonical_key_material,
)
from ..request_cache.global_plan import build_global_cache_plan
from .ports import CaptureKey

logger = logging.getLogger(__name__)

_KEY_PREFIX_LENGTH: Final = 12


def build_capture_key(*, body: dict[str, Any], plugin: ProviderPluginBase) -> CaptureKey | None:
    plan = build_global_cache_plan(
        body=body,
        plugin=plugin,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )
    if isinstance(plan, CacheBypass):
        return None
    try:
        # The plan does not return the rules and the modes, so they are fetched again here.
        rules = tuple(plugin.chat_parameter_rules(model=str(body["model"]), auth_type=None))
        modes = tuple(plugin.available_auth_modes())
        dto = build_global_cache_key_dto(
            provider=plugin.custom_llm_provider,
            body=body,
            rules=rules,
            projection=plugin.global_cache_projection,
            provider_auth_modes=modes,
        )
        if isinstance(dto, CacheBypass):
            return None
        material = canonical_key_material(dto)
    except Exception:
        return None
    return _checked_key(plan, material)


def _checked_key(plan: GlobalCacheKeyResult, material: str) -> CaptureKey | None:
    # Defence: the key and the prompt must describe one call.
    if hashlib.sha256(material.encode("utf-8")).hexdigest() != plan.key_hash:
        logger.warning(
            "capture key mismatch: material does not hash to the plan key=%s…",
            plan.key_hash[:_KEY_PREFIX_LENGTH],
        )
        return None
    return CaptureKey(key_hash=plan.key_hash, material=material)
