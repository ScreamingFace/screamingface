"""The credential-type vocabulary, shared by Profiles, Connections and every provider plugin.

# FEATURE: OME-1209 Stage E, E2a — moved out of `profile_models.py` so the gateway's core and its
# plugins no longer depend on the legacy Profile module.
"""

from __future__ import annotations

from typing import Literal

# INVARIANT: AuthType is the PERSISTED credential type — the only values a stored
# Profile or OAuthConnection may hold, and the only ones a credential strategy can
# be built for. AuthMode is the RESOLVED outcome, which additionally admits "none"
# for a provider that needs no upstream credential at all (OME-636).
#
# WHY two literals instead of widening one: "none" must be unforgeable. Keeping it
# out of AuthType means no persisted model and no request schema ever accepts it,
# so a client cannot declare it and an operator cannot store it — enforced by the
# type checker rather than by a validation rule someone can forget to write.
# WHY "none" is narrow: it means no PROVIDER credential. It says nothing about the
# caller's own authentication to AIGateway, which is unchanged.
AuthType = Literal["oauth", "api_key"]
AuthMode = Literal["oauth", "api_key", "none"]
