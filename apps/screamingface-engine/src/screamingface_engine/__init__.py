"""screamingface-engine backend — the App: mints tokens, upgrades WebSocket
connections, and schedules Runner Jobs (REST + WS control plane)."""

import importlib.metadata

# WHY no fallback: a source tree that was never installed has no version to state, so the import
# fails loudly rather than seal a copy with a wrong version.
__version__ = importlib.metadata.version("screamingface-engine")
"""The installed engine version. A frozen copy records it at seal (E14 Q28)."""
