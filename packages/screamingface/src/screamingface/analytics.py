"""Explicit analytics preferences. No account identity or login is involved."""

import os
import sys

from screamingface._analytics.local import LocalConsentStore, config_path
from screamingface._analytics.ports import Consent

_process_disabled = False
_session_only = False


def _disabled() -> bool:
    value = os.getenv("DO_NOT_TRACK", "").strip().lower()
    return _process_disabled or value not in {"", "0", "false", "no", "off"}


def _consent() -> Consent:
    if _disabled():
        return Consent()
    if "google.colab" in sys.modules:
        from screamingface._analytics.colab import bridge

        return bridge().read()
    return Consent("accepted") if _session_only else LocalConsentStore(config_path()).read()


def status() -> dict:
    """Return choice and effective state without creating files or identifiers."""
    if "google.colab" in sys.modules:
        from screamingface._analytics.colab import bridge

        saved = bridge().read()
        return {
            "choice": saved.choice,
            "enabled": not _disabled() and saved.choice == "accepted",
            "scope": "browser",
            "installation_id": None,
            "persistent_id": saved.installation_id,
            "pending": bridge().pending,
        }
    saved = LocalConsentStore(config_path()).read()
    active = _consent()
    return {
        "choice": "accepted" if _session_only else saved.choice,
        "enabled": active.choice == "accepted",
        "scope": "session" if _session_only else "installation",
        "installation_id": active.installation_id,
    }


def enable(*, persist: bool = True) -> None:
    """Opt in and print confirmation; use status() for details. Colab waits up to 3s."""
    result = _enable(persist=persist)
    print(
        "Analytics enabled."
        if result["enabled"]
        else "Couldn't enable analytics; tracking remains off."
    )


def _enable(*, persist: bool = True) -> dict:
    """Shared consent operation; the CLI renders its result as JSON."""
    global _process_disabled, _session_only
    _process_disabled = False
    if _disabled():
        return status()
    if "google.colab" in sys.modules:
        from screamingface._analytics.colab import bridge

        if not persist:
            raise ValueError(
                "Colab analytics requires browser consent; persist=False is unsupported"
            )
        bridge().accept()
        return status()
    _session_only = not persist
    if persist:
        LocalConsentStore(config_path()).change("accepted")
    return status()


def disable(*, process_only: bool = False) -> None:
    """Stop tracking and print confirmation; use status() for persistence details."""
    result = _disable(process_only=process_only)
    message = "Analytics disabled."
    if process_only:
        message = "Analytics disabled for this process."
    elif result.get("pending"):
        message += " Saving your choice in the browser."
    elif result.get("scope") == "browser" and result["choice"] != "declined":
        message += " Couldn't save your choice in the browser."
    print(message)


def _disable(*, process_only: bool = False) -> dict:
    """Stop analytics; by default also save decline and discard the installation ID."""
    global _process_disabled, _session_only
    _process_disabled, _session_only = True, False
    from screamingface._analytics.wiring import clear

    clear()
    if "google.colab" in sys.modules:
        from screamingface._analytics.colab import bridge

        bridge().stop(persist=not process_only)
        return status()
    if not process_only:
        LocalConsentStore(config_path()).change("declined")
    return status()


def reset_identifier() -> dict:
    """Rotate an accepted installation ID without joining old and new activity."""
    from screamingface._analytics.wiring import clear

    clear()
    if "google.colab" in sys.modules:
        from screamingface._analytics.colab import bridge

        if not _disabled() and bridge().read().choice == "accepted":
            bridge().control("reset")
        return status()
    if not _disabled() and not _session_only:
        LocalConsentStore(config_path()).change("accepted", rotate=True)
    return status()


__all__ = ["status", "enable", "disable", "reset_identifier"]
