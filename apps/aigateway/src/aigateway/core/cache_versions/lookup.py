"""The version lookup adapter (OME-1307, GW-replay): Tortoise implementation of the port.

FEATURE: OME-1307 (E14) - replay finds one call in a frozen version by its key hash.

INVARIANT (CV-D6, RP-D5): when a key repeats in a version, the LOWEST ``first_ordinal`` wins, so a
replay of a repeated call always gets the answer that the original run saw first.
INVARIANT (CV-D10): the blob body is model output. It is returned as data, never parsed or acted
on, and never logged. A log line carries a key prefix only.

AIDEV-NOTE: the query rides the unique index ``(version_id, key_hash, blob_id)`` of migration 0013
(the NFR is 30 ms p99). ``blob_id`` is the FK column of ``blob`` (D8).
"""

from __future__ import annotations

import json
import logging
from typing import Final
from uuid import UUID

from .models import CacheVersion, CacheVersionEntry
from .ports import VersionHit

logger = logging.getLogger(__name__)

_KEY_PREFIX_LENGTH: Final = 12


class TortoiseCacheVersionLookup:
    async def version_exists(self, version_id: UUID) -> bool:
        return await CacheVersion.exists(id=version_id)

    async def find(self, version_id: UUID, key_hash: str) -> VersionHit | None:
        entry = (
            await CacheVersionEntry.filter(version_id=version_id, key_hash=key_hash)
            .order_by("first_ordinal", "blob_id")
            .select_related("blob")
            .first()
        )
        if entry is None:
            return None
        response = json.loads(entry.blob.response_json)
        if not isinstance(response, dict):
            logger.warning(
                "cache version blob is not a JSON object key=%s…", key_hash[:_KEY_PREFIX_LENGTH]
            )
            return None
        return VersionHit(response=response, metadata_json=entry.blob.metadata_json)
