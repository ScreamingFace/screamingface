"""Explicit analytics preferences. No account identity or login is involved."""

import os
import sys

from screamingface._analytics.local import LocalConsentStore, config_path
from screamingface._analytics.ports import Consent

_process_disabled = False
_session_only = False


def _disabled() -> bool:
    value = os.getenv("DO_NOT_TRACK", "").strip().lower()
    return (
        _process_disabled
        or "google.colab" in sys.modules
        or value not in {"", "0", "false", "no", "off"}
    )


def _consent() -> Consent:
    if _disabled():
        return Consent()
    if _session_only:
        return Consent("accepted")
    return LocalConsentStore(config_path()).read()


def status() -> dict:
    """Return local choice and effective state without creating files or identifiers."""
    saved = LocalConsentStore(config_path()).read()
    active = _consent()
    return {
        "choice": "accepted" if _session_only else saved.choice,
        "enabled": active.choice == "accepted",
        "scope": "session" if _session_only else "installation",
        "installation_id": active.installation_id,
    }


def enable(*, persist: bool = True) -> dict:
    """Opt in to four anonymous activity events; persist=False accepts for this process."""
    global _process_disabled, _session_only
    _process_disabled = False
    if _disabled():
        return status()
    _session_only = not persist
    if persist:
        LocalConsentStore(config_path()).change("accepted")
    return status()


def disable(*, process_only: bool = False) -> dict:
    """Stop analytics; by default also save decline and discard the installation ID."""
    global _process_disabled, _session_only
    _process_disabled, _session_only = True, False
    from screamingface._analytics.wiring import clear

    clear()
    if not process_only:
        LocalConsentStore(config_path()).change("declined")
    return status()


def reset_identifier() -> dict:
    """Rotate an accepted installation ID without joining old and new activity."""
    from screamingface._analytics.wiring import clear

    clear()
    if not _disabled() and not _session_only:
        LocalConsentStore(config_path()).change("accepted", rotate=True)
    return status()


__all__ = ["status", "enable", "disable", "reset_identifier"]
