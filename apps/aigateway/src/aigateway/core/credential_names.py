"""Stored-credential locators (OME-1209 Stage E, E2a — moved out of `profile_models.py`).

# INVARIANT: both shapes address rows that already exist — blobs in `credential_blobs` and legacy
# index documents. Changing either string orphans every stored credential it names.
# WHY `profile_id_for` keeps its name: it computes the stored locator of a migrated blob, which E5
# still needs after the Profile row is gone.
"""

from __future__ import annotations


def profile_id_for(account_id: str, provider: str, name: str) -> str:
    return f"{account_id}:{provider}:{name}"


def credential_name_for(account_id: str, name: str) -> str:
    return f"{account_id}:{name}"
