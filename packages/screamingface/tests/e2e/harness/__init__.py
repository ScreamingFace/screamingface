"""E2E replay harness (OME-961): run a benchmark end-to-end from recorded responses.

Think of it as a cassette deck for the whole stack: a *backend* (``ports.ReplayBackend``)
serves previously recorded model responses over the AI Gateway's real HTTP surface, the
real engine is pointed at it, and the SDK drives an evaluation exactly the way a notebook
does. Zero provider keys exist anywhere, so a cache miss is a loud ``profile_not_found``
error — spend is impossible by construction, not by discipline.

Modules:

- ``ports``    — the ONE seam every backend implements (``start() -> base_url``, ``stop()``).
- ``tape``     — the recorded-exchange data model shared with the OME-962 FakeGateway.
- ``goldens``  — golden reports and the compare-order contract (expression SHA first).
- ``cache_seeded`` — the happy-path backend: real aigateway + Postgres testcontainer +
  snapshot loaded through the OME-951/952 admin route.
- ``stack``    — boots the engine against a backend's base_url and yields the stack URLs.
"""
