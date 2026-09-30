"""The system registry core: names, pins, ports and `RegistryService`.

FEATURE: OME-1307 (E14). INVARIANT: standard library only (C11-SB-2).
"""

from .errors import (
    InvalidPin,
    InvalidSystemName,
    InvalidUrl4,
    NotSystemOwner,
    PinNotFound,
    RegistryConflict,
    RegistryError,
    RegistryWriteConflict,
    SystemNameTaken,
    SystemNotFound,
    Url4TooLarge,
)
from .model import (
    BoardVisibility,
    DatePin,
    NamePin,
    Pin,
    Resolution,
    ResolutionOutcome,
    RevisionPin,
    RevisionRef,
    SystemAlreadyNamed,
    SystemIdentity,
    SystemRef,
)
from .names import normalize_system_name, suggest_name
from .pins import parse_pin
from .ports import SystemFingerprinter, SystemRegistry, SystemRepository
from .service import MAX_URL4_CHARS, RegistryService

__all__ = [
    "MAX_URL4_CHARS",
    "BoardVisibility",
    "DatePin",
    "InvalidPin",
    "InvalidSystemName",
    "InvalidUrl4",
    "NamePin",
    "NotSystemOwner",
    "Pin",
    "PinNotFound",
    "RegistryConflict",
    "RegistryError",
    "RegistryService",
    "RegistryWriteConflict",
    "Resolution",
    "ResolutionOutcome",
    "RevisionPin",
    "RevisionRef",
    "SystemAlreadyNamed",
    "SystemFingerprinter",
    "SystemIdentity",
    "SystemNameTaken",
    "SystemNotFound",
    "SystemRef",
    "SystemRegistry",
    "SystemRepository",
    "Url4TooLarge",
    "normalize_system_name",
    "parse_pin",
    "suggest_name",
]
