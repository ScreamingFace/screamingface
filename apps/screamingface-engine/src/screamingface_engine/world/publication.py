"""Which declared routes the Engine publishes, and the review that keeps private ones private.

FEATURE (OME-1770, hosted BYOM Unit 2): executable membership is not publication. A route declared
`public_schema = false` is registered and runs like any other, but it is left off every surface
the Engine shares with all callers: the shared OpenAPI, the `/metrics` path labels and the details
answer an ungranted caller gets. Each surface needs the private set in its own form, so this module
derives all three from ONE parsed world.

INVARIANT: privacy comes only from the declaration. Nothing here reads a provider prefix, so a
configured-endpoint id declared without the flag is public, and the review below is what catches it.

WHY the review reads the Gateway's file: every configured target there is private, because the
Gateway grants it to named accounts, and neither process holds both files. Only `endpoints[].id`
and `targets[].alias` are read, and a refusal never quotes the file, which also holds origins.
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Mapping

from screamingface_engine.world.config import WorldConfig, routes_for
from screamingface_engine.world.models.registry import decode_route_id


class PublicationReviewError(ValueError):
    """The Gateway's endpoints file cannot be read for review; the message quotes none of it."""


def private_route_ids(config: WorldConfig) -> frozenset[str]:
    """The url4-route ids declared `public_schema = false`."""
    section = config.aigateway
    if section is None:
        return frozenset()
    return frozenset(model.id for model in section.models if not model.public_schema)


def private_mount_paths(config: WorldConfig) -> frozenset[str]:
    """The same routes as App mount paths, `"/" + id`, as :func:`routes_for` builds them."""
    section = config.aigateway
    if section is None:
        return frozenset()
    return frozenset(
        path for path, model in routes_for(section.models).items() if not model.public_schema
    )


def private_model_ids(config: WorldConfig) -> frozenset[str]:
    """The same routes as REAL Gateway ids, the form the catalog compares and forwards."""
    return frozenset(decode_route_id(route_id) for route_id in private_route_ids(config))


def gateway_target_ids(document: str) -> frozenset[str]:
    """Every `<endpoint-id>/<alias>` the Gateway's endpoints file configures, enabled or not."""
    try:
        parsed = tomllib.loads(document)
    except tomllib.TOMLDecodeError:
        raise PublicationReviewError("the endpoints file is not valid TOML") from None
    endpoints = parsed.get("endpoints", [])
    if not isinstance(endpoints, list):
        raise PublicationReviewError("`endpoints` must be an array of tables")
    ids: set[str] = set()
    for position, endpoint in enumerate(endpoints, start=1):
        if not isinstance(endpoint, Mapping):
            raise PublicationReviewError(f"endpoint #{position} is not a table")
        targets = endpoint.get("targets")
        if not isinstance(targets, list) or not all(isinstance(t, Mapping) for t in targets):
            raise PublicationReviewError(f"endpoint #{position} has no array of target tables")
        endpoint_id = _text(endpoint, "id", position)
        ids.update(f"{endpoint_id}/{_text(target, 'alias', position)}" for target in targets)
    return frozenset(ids)


def declared_targets(config: WorldConfig, targets: Collection[str]) -> frozenset[str]:
    """The Gateway configured targets this world declares, as REAL Gateway ids."""
    section = config.aigateway
    if section is None:
        return frozenset()
    return frozenset(decode_route_id(model.id) for model in section.models) & frozenset(targets)


def review_endpoint_routes(config: WorldConfig, targets: Collection[str]) -> tuple[str, ...]:
    """One problem per unsafe declaration of a Gateway configured target, or none.

    A target the world does not declare is not a problem: it cannot run through this Engine, so
    there is nothing to publish.
    """
    section = config.aigateway
    if section is None:
        return ()
    declared = declared_targets(config, targets)
    problems: list[str] = []
    for model in sorted(section.models, key=lambda item: item.id):
        if decode_route_id(model.id) not in declared:
            continue
        if model.public_schema:
            problems.append(
                f"{model.id}: a configured endpoint target must declare public_schema = false, "
                "or the shared schema publishes it"
            )
        if model.web_search:
            problems.append(
                f"{model.id}: a configured endpoint target must declare web_search = false; its "
                "chat contract refuses the search tools"
            )
    return tuple(problems)


def _text(table: Mapping[str, object], key: str, position: int) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise PublicationReviewError(f"endpoint #{position} has no `{key}` string")
    return value


__all__ = [
    "PublicationReviewError",
    "declared_targets",
    "gateway_target_ids",
    "private_model_ids",
    "private_mount_paths",
    "private_route_ids",
    "review_endpoint_routes",
]
