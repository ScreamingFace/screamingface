from __future__ import annotations

import logging
from typing import Any, Protocol

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class SupportsCredentialPersistence(Protocol):
    async def persist_credentials(self, credentials: dict[str, Any]) -> None: ...

    def credential_service(self) -> str: ...


async def persist_credentials_or_503(
    strategy: SupportsCredentialPersistence,
    credentials: dict[str, Any],
    *,
    description: str,
) -> None:
    try:
        await strategy.persist_credentials(credentials)
    except Exception as exc:
        # Store adapters may echo credentials in exception text; log only type + service.
        logger.error(
            "Failed to persist %s for service %s: %s",
            description,
            strategy.credential_service(),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "credential_store_unavailable",
                "message": f"Could not store {description}. Try again.",
            },
        ) from exc
