"""The stored-credential name tests seed blobs under (moved out of `aigateway.core` at L4b).

# WHY a test helper (OME-1138 close-out, L4b): production addresses every stored blob through its
# Connection's stored locator and never computes a name, so only tests still spell one.
# INVARIANT: the shape is the address production stores in a Connection's locator
# (`credential_locator_for`). Changing it would make a seeded blob miss the Connection that reads
# it; `test_neutral_credential_vocabulary.py` pins the two together.
"""

from __future__ import annotations


def credential_name_for(account_id: str, name: str) -> str:
    return f"{account_id}:{name}"
