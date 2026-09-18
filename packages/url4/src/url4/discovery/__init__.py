"""The node's discovery surface: the three `.well-known` documents.

`wellknown` builds one document; `compose` assembles the set for one caller; `resolver`
turns a mount table into the mounts those builders take. Every module here is stdlib-only
— fetching is injected, so this package never learns about HTTP.
"""

from url4.discovery.carrier import (
    ATTACH_CONFIG_KEY,
    HEADER_PREFIX,
    CarrierError,
    coerce,
    from_attach_frame,
    from_headers,
)
from url4.discovery.catalog import (
    CATALOG_ID,
    Defect,
    LintCode,
    NotACatalog,
    catalog_of,
    format_defects,
    is_catalog,
    is_group,
    is_leaf,
    lint_catalog,
)
from url4.discovery.compose import (
    Discovery,
    Document,
    MountNotFound,
    MountResolver,
    etag_of,
)
from url4.discovery.problem import PROBLEM_MEDIA_TYPE, PROBLEM_TYPE, config_rejected
from url4.discovery.resolver import MountSpec, TableResolver, read_mount_table
from url4.discovery.scope import (
    Code,
    Violation,
    enforce,
    is_secret_ref,
    resolve_item,
    settable_by,
    walk_config,
)
from url4.discovery.wellknown import (
    CAPABILITIES_PATH,
    CONFIG_PATH,
    POLICY_PATH,
    WELL_KNOWN_PATHS,
    Mount,
    ProcessorType,
    Status,
    canonical,
    read_endpoint_card,
)

__all__ = [
    "ATTACH_CONFIG_KEY",
    "CAPABILITIES_PATH",
    "CATALOG_ID",
    "CONFIG_PATH",
    "CarrierError",
    "Code",
    "Defect",
    "Discovery",
    "Document",
    "HEADER_PREFIX",
    "LintCode",
    "Mount",
    "MountNotFound",
    "MountResolver",
    "MountSpec",
    "NotACatalog",
    "POLICY_PATH",
    "PROBLEM_MEDIA_TYPE",
    "PROBLEM_TYPE",
    "ProcessorType",
    "Status",
    "TableResolver",
    "Violation",
    "WELL_KNOWN_PATHS",
    "canonical",
    "catalog_of",
    "coerce",
    "config_rejected",
    "enforce",
    "etag_of",
    "format_defects",
    "from_attach_frame",
    "from_headers",
    "is_catalog",
    "is_group",
    "is_leaf",
    "is_secret_ref",
    "lint_catalog",
    "read_endpoint_card",
    "read_mount_table",
    "resolve_item",
    "settable_by",
    "walk_config",
]
