"""The pure capture key of one chat call (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - a traced call is captured under the SAME key hash that the live global
cache uses for the same body, so a later replay can find the call again by that hash.

INVARIANT: PURE and TOTAL. No I/O; it reads no account, profile or credential; it never raises.

WHY it calls ``build_global_cache_plan_with_material``: every eligibility gate of the live cache
applies unchanged, and the key hash and the stored material come from ONE canonicalisation, so they
cannot drift. The operator switch and the caller opt-out are ignored on purpose
(``participate=True``, ``cache_enabled=True``). An opted-out call (``use-cache: false``) must still
have a key, because CV-H1 keeps its prompt in ``request_cache_prompt``, and capture must work when
the live cache is off (local mode).

AIDEV-NOTE (exception to a documented rule): the docstrings of ``canonical_key_material``
(``request_cache/global_keys.py``) and ``canonical_material`` (``request_cache/canonical.py``) say
the material is "never persisted". E14 persists this material in ``request_cache_prompt`` on
purpose (``erd.md`` 3.1). The ``*_with_material`` functions in ``request_cache/`` exist only for
this caller. The material is stored, never logged.

Consequence: a provider without a global-cache projection (the base default is ``CacheBypass``:
gemini, codex, antigravity, ollama today), a streaming body (``BYPASS_STREAM``) and every other
unkeyable body get NO capture key. Such a call still gets a capture row with ``key_hash = NULL``,
and GW-freeze counts it as missing (plan OD-2, spec gap SG-1).
"""

from __future__ import annotations

from typing import Any

from ..cache_ports import CacheBypass
from ..plugin_base import ProviderPluginBase
from ..request_cache.global_controls import GlobalCacheControls
from ..request_cache.global_plan import build_global_cache_plan_with_material
from .ports import CaptureKey


def build_capture_key(*, body: dict[str, Any], plugin: ProviderPluginBase) -> CaptureKey | None:
    planned = build_global_cache_plan_with_material(
        body=body,
        plugin=plugin,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )
    if isinstance(planned, CacheBypass):
        return None
    plan, material = planned
    return CaptureKey(key_hash=plan.key_hash, material=material)
