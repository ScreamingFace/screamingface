"""screamingface-engine backend — the App: mints tokens, upgrades WebSocket
connections, and schedules Runner Jobs (REST + WS control plane)."""

import importlib.metadata


def engine_version() -> str | None:
    """The installed engine version, or ``None`` for a source tree that was never installed.

    FEATURE: E14 Q28. A frozen copy records it at seal.
    WHY at call time, not at import: the SDK tests import the engine from source, without its
    package metadata, and that import must not fail. An unknown version seals with no provenance.
    """
    try:
        return importlib.metadata.version("screamingface-engine")
    except importlib.metadata.PackageNotFoundError:
        return None
