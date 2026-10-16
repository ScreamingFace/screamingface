from __future__ import annotations

import json
import logging
import re

from aigateway.core.json_bounds import JsonBoundsError, assert_bounded_json
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
)
from aigateway.core.plugin_base import ModelEntry

from .settings import LocalPluginSettings

_UPSTREAM_MODEL_ID = re.compile(r"[A-Za-z0-9_.:-]+(?:/[A-Za-z0-9_.:-]+)*", re.ASCII)
logger = logging.getLogger(__name__)


def upstream_model_id(model: object) -> str | None:
    # INVARIANT: `~` belongs only to Engine's encoded route form. Accepting it from
    # upstream would make raw and route identities ambiguous at the URL4 boundary.
    if not isinstance(model, str) or not model.startswith("local/"):
        return None
    upstream = model.removeprefix("local/")
    if "~" in upstream or _UPSTREAM_MODEL_ID.fullmatch(upstream) is None:
        return None
    return upstream


def _parse_listing(body: str, *, limits: DiscoveryLimits) -> tuple[ModelEntry, ...]:
    if len(body.encode("utf-8")) > limits.max_bytes:
        raise DiscoveryError("oversized")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, RecursionError):
        raise DiscoveryError("malformed_json") from None
    try:
        assert_bounded_json(
            payload,
            max_depth=limits.max_json_depth,
            max_nodes=limits.max_json_nodes,
        )
    except JsonBoundsError as exc:
        raise DiscoveryError(exc.reason) from None
    if not isinstance(payload, dict) or payload.get("object") != "list":
        raise DiscoveryError("malformed_json")
    data = payload.get("data")
    if not isinstance(data, list):
        raise DiscoveryError("malformed_json")
    seen: set[str] = set()
    entries: list[ModelEntry] = []
    skipped = 0
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise DiscoveryError("malformed_json")
        upstream = row["id"]
        # WHY skip, not fail the refresh: LM Studio identifiers are user-defined, but
        # only URL4-routeable identities can cross into Engine. One unsupported alias
        # must not hide every healthy model served by the same process.
        if upstream_model_id(f"local/{upstream}") is None or upstream in seen:
            skipped += 1
            continue
        seen.add(upstream)
        entries.append(
            ModelEntry(
                model_name=f"local/{upstream}",
                litellm_params={"model": upstream},
            )
        )
    if skipped:
        logger.warning(
            "local models skipped",
            extra={"skipped_model_count": skipped},
        )
    return tuple(entries)


async def discover_local_models(
    settings: LocalPluginSettings,
    *,
    client: DiscoveryHttpClient,
    limits: DiscoveryLimits | None = None,
) -> tuple[ModelEntry, ...]:
    bounds = limits if limits is not None else DiscoveryLimits()
    response = await client.get(
        f"{settings.base_url}/models",
        timeout_s=bounds.timeout_s,
        max_bytes=bounds.max_bytes,
    )
    if response.status != 200:
        raise DiscoveryError("bad_status", status=response.status)
    if response.content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise DiscoveryError("bad_content_type")
    return _parse_listing(response.body, limits=bounds)
