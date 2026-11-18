"""Read-only seed check: prints the dead seeds and the new models of the tracked labs.

Run from apps/aigateway: uv run python scripts/check_openrouter_seeds.py

The command reads the public OpenRouter catalogue over the network and changes no file.
It is a manual report, not a CI gate, because it needs the network.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from aigateway.plugins.openrouter_provider.discovery import MODELS_URL
from aigateway.plugins.openrouter_provider.settings import (
    GATEWAY_MODEL_PREFIX,
    OpenRouterPluginSettings,
    is_valid_upstream_model_id,
)

CATALOG_URL = f"{MODELS_URL}?output_modalities=text"
TRACKED_AUTHORS: frozenset[str] = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "qwen",
        "mistralai",
        "deepseek",
        "x-ai",
        "meta",
        "moonshotai",
        "z-ai",
        "tencent",
        "minimax",
        "xiaomi",
        "stepfun",
    }
)


@dataclass(frozen=True, slots=True)
class SeedReport:
    """dead: seeds not in the catalogue, in seed order; new: (gateway id, created), newest first."""

    dead: tuple[str, ...]
    new: tuple[tuple[str, int], ...]


def _created(row: Mapping[str, object]) -> int | None:
    created = row.get("created")
    # WHY: bool is a subclass of int in Python, so True would pass as a timestamp.
    if isinstance(created, int) and not isinstance(created, bool):
        return created
    return None


def _is_plain_text_candidate(model_id: str, row: Mapping[str, object]) -> bool:
    # WHY: a variant (":free") is not a new model. An alias ("~author/model") needs no test
    # of its own: its author starts with "~", so it fails the author test below.
    if not is_valid_upstream_model_id(model_id) or ":" in model_id:
        return False
    if model_id.split("/", 1)[0] not in TRACKED_AUTHORS:
        return False
    architecture = row.get("architecture")
    return isinstance(architecture, Mapping) and architecture.get("output_modalities") == ["text"]


def seed_report(rows: Sequence[Mapping[str, object]], seeds: Sequence[str]) -> SeedReport:
    """Compare the seeds with the catalogue rows; the rows are not changed."""
    catalogue: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("id")
        if isinstance(model_id, str):
            catalogue.setdefault(model_id, row)
    seed_ids = {seed.removeprefix(GATEWAY_MODEL_PREFIX) for seed in seeds}
    dead = tuple(seed for seed in seeds if seed.removeprefix(GATEWAY_MODEL_PREFIX) not in catalogue)
    # WHY: only seeds in the catalogue set the threshold; a dead seed has no date to compare.
    threshold = max(
        (
            created
            for seed_id in seed_ids
            if seed_id in catalogue and (created := _created(catalogue[seed_id])) is not None
        ),
        default=None,
    )
    new: list[tuple[str, int]] = []
    for model_id, row in catalogue.items():
        if model_id in seed_ids or not _is_plain_text_candidate(model_id, row):
            continue
        created = _created(row)
        if created is None or (threshold is not None and created <= threshold):
            continue
        new.append((GATEWAY_MODEL_PREFIX + model_id, created))
    ordered = sorted(new, key=lambda pair: (-pair[1], pair[0]))
    return SeedReport(dead=dead, new=tuple(ordered))


def _iso_date(created: int) -> str:
    return datetime.fromtimestamp(created, tz=UTC).date().isoformat()


def main() -> None:
    response = httpx.get(CATALOG_URL, timeout=30.0)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list):
        raise SystemExit("unexpected OpenRouter catalogue payload: no 'data' list")
    # INVARIANT: the report needs the complete catalogue. With only one page of it, a live
    # seed is reported as dead and a new model is not reported, and nothing shows the error.
    links = payload.get("links")
    total = payload.get("total_count")
    if (isinstance(links, Mapping) and links.get("next") is not None) or (
        isinstance(total, int) and not isinstance(total, bool) and total > len(data)
    ):
        raise SystemExit("the OpenRouter catalogue answer is paged: the report needs all the rows")
    report = seed_report(data, OpenRouterPluginSettings().default_models)
    print(f"Dead seeds (not in the OpenRouter catalogue): {len(report.dead)}")
    for gateway_id in report.dead:
        print(f"  {gateway_id}")
    print(f"New models of the tracked labs (newer than the newest seed): {len(report.new)}")
    for gateway_id, created in report.new:
        print(f"  {gateway_id}  {_iso_date(created)}")


if __name__ == "__main__":
    main()
