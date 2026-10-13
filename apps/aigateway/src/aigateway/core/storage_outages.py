"""The exceptions that mean "the database could not answer" — an outage, not a bug.

# WHY a list of its own: Tortoise's asyncpg client translates only syntax/access and data errors
# into `OperationalError` (and a missing database into `DBConnectionError`); a dropped connection,
# a server restart, an exhausted server or a socket timeout reaches the caller as the driver's own
# exception. A refusal that promises "temporarily unavailable" must recognise those too.
# INVARIANT: only storage-availability failures belong here. A programming error is never on this
# list, so it still surfaces as a 500 instead of passing for an outage.
# AIDEV-NOTE: `OperationalError` also carries schema drift (a missing migration): it is reported as
# unavailable — the request cannot be served either way, and the log keeps the class name.
"""

from __future__ import annotations

from asyncpg import exceptions as asyncpg_exceptions
from tortoise.exceptions import DBConnectionError, OperationalError

STORAGE_OUTAGES: tuple[type[Exception], ...] = (
    OperationalError,
    DBConnectionError,
    asyncpg_exceptions.PostgresConnectionError,
    asyncpg_exceptions.OperatorInterventionError,
    asyncpg_exceptions.InsufficientResourcesError,
    asyncpg_exceptions.InterfaceError,
    # `ConnectionError` and `TimeoutError` are both `OSError`s.
    OSError,
)

__all__ = ["STORAGE_OUTAGES"]
