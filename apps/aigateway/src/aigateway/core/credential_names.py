"""Stored-credential locators (OME-1209 Stage E, E2a — moved out of `profile_models.py`).

# INVARIANT: the shape addresses blobs that already exist in `credential_blobs`. Changing the
# string orphans every stored credential it names.
"""

from __future__ import annotations


def credential_name_for(account_id: str, name: str) -> str:
    return f"{account_id}:{name}"
