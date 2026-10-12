"""screamingface-engine backend — the App: mints tokens, upgrades WebSocket
connections, and schedules Runner Jobs (REST + WS control plane)."""

import importlib.metadata

__version__ = importlib.metadata.version("screamingface-engine")
"""The installed engine version. A frozen copy records it at seal (E14 Q28)."""
