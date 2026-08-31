from __future__ import annotations

import json
from pathlib import Path


def _prod_values_text() -> str:
    return (Path(__file__).resolve().parents[2] / "charts/aigateway/values-prod.yaml").read_text()


def _extra_env_json_value(name: str) -> dict[str, int]:
    lines = _prod_values_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() not in {f"name: {name}", f"- name: {name}"}:
            continue
        for candidate in lines[index + 1 : index + 4]:
            stripped = candidate.strip()
            if stripped.startswith("value: "):
                raw = stripped.removeprefix("value: ").strip().strip("'").strip('"')
                return json.loads(raw)
    raise AssertionError(f"{name} not found in prod extraEnv")


def test_prod_sets_finite_openrouter_provider_concurrency_cap() -> None:
    # STORY: OME-921's cloud config must apply the existing provider cap override.
    override = _extra_env_json_value("AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES")

    assert override == {"openrouter": 50}
    assert override["openrouter"] > 0
