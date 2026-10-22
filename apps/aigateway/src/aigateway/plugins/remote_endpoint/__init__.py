"""Operator-approved remote inference endpoints, one provider instance per endpoint.

# INVARIANT: deliberately not a `*_provider` package and exports no `PLUGIN`, so the bundled loader
# never discovers it; only `aigateway.provider_composition` builds its instances.
"""
