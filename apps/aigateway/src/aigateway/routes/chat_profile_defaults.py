"""Retained shims from the saved-defaults era: no production caller since OME-1323 (Stage C).

``profile_defaults_for_key`` read a caller's stored Profile defaults ahead of the cache so the
global key could cover the EFFECTIVE request (OME-305 §57); ``_parameter_rejection_exception``
attributed a classification failure to a stored default (OME-638). Stage C (D2) retired both
behaviours: request parameters are the caller's, the chat route reads no stored default and
merges nothing, and a parameter rejection is always the caller's own.

AIDEV-NOTE: both names stay importable and behave exactly as before until Stage E removes them
together with ``defaults_for`` / ``apply_defaults`` (OME-1209). Do not wire either back into the
chat route: a stored value merged ahead of the key re-opens the wrong-hit and the
refuse-a-value-the-caller-never-sent classes Stage C closed.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..core.parameter_projection import UnsupportedParametersError
from ..core.profile_models import ProfileDefaults
from ..core.provider_access import Selector, provider_access_for


async def profile_defaults_for_key(
    request: Request,
    *,
    account_id: str,
    provider: str,
    profile_name: str,
) -> ProfileDefaults | None:
    """Read ONLY this caller's stored defaults, before any credential is resolved.

    OME-305 ruling 57: ``cache_behavior="keyed"`` disciplined only CALLER-SUPPLIED
    values, because the defaults merge ran after the key was built and a default fills
    only an omitted path. Two callers could both POST a bare ``{model, messages}`` and
    collide on one key while their profiles asked the provider two different questions
    — a wrong ANSWER, not a missed saving. Merging before the key closes that, and
    this is the narrowest read that makes the merge possible.

    INVARIANT: never raises, and never inspects ``ProfileState`` — the port's
    ``defaults_for`` carries both guarantees. ``None`` means the index could not be READ
    — never "this profile has no defaults", which is an empty ``ProfileDefaults``. That
    distinction IS the fail-safe: the caller must bypass the cache instead, and then merge
    the defaults Stage 2 resolves so the request still DISPATCHES with them.

    AIDEV-NOTE: a hit costs one profile-index read, and that index is itself a
    ``credential_blobs`` row — so a hit performs one master-key decryption where it
    previously performed none. No provider credential is read, decrypted or injected,
    and no auth mode is resolved; that is the property the inversion needs.
    """
    return await provider_access_for(request.app).defaults_for(
        account_id, provider, Selector.from_header(profile_name)
    )


def _parameter_rejection_exception(
    exc: UnsupportedParametersError,
    *,
    provider: str,
    profile_name: str,
    default_paths: frozenset[str],
) -> HTTPException:
    """Render a classification failure against the source that actually caused it.

    WHY two codes (OME-638): profile defaults are classified in the SAME pass as
    caller fields, so one rejection map can mix an operator-configuration fault
    with a request fault. Reporting a stored default under
    ``unsupported_parameters`` would send the caller hunting through a request
    that does not contain the named field, so a rejection caused solely by
    defaults gets its own code and names the profile instead. 400 either way,
    matching ``api_key_not_supported`` — stored configuration this provider
    cannot serve is a bad request, not a server fault.

    INVARIANT: the caller-facing ``rejected`` map lists only paths the CALLER
    supplied. Defaults occupy only omitted paths, so the two sets are disjoint and
    neither error can echo the other's fields.

    WHY a caller fault wins when both are present: the request has to be fixed
    regardless, and it is the only half the caller can act on. The profile half is
    logged for the operator rather than dropped.
    """
    caller_rejected = {
        path: reason for path, reason in exc.rejected.items() if path not in default_paths
    }
    if caller_rejected:
        return HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_parameters",
                "provider": provider,
                "rejected": caller_rejected,
                "message": (
                    "one or more parameters are not enabled for this model; "
                    "see the model parameter contract"
                ),
            },
        )
    return HTTPException(
        status_code=400,
        detail={
            "code": "invalid_profile_defaults",
            "provider": provider,
            "profile": profile_name,
            "rejected": exc.rejected,
            "message": (
                "the stored profile defaults are not enabled for this model; "
                "see the model parameter contract"
            ),
        },
    )
