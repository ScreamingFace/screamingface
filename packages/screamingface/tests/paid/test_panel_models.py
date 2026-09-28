"""Free guards for the paid lane — everything checkable without a key or a stack."""

from __future__ import annotations

from pathlib import Path

from _panel import MEMBER_MODELS, SYNTHESIZER_MODEL

_SEEDS_FILE: Path = (
    Path(__file__).resolve().parents[4]
    / "apps"
    / "aigateway"
    / "src"
    / "aigateway"
    / "plugins"
    / "openrouter_provider"
    / "settings.py"
)


def test_panel_models_are_gateway_seeds() -> None:
    """INVARIANT: every pinned panel model is an aigateway seed — checked for $0.

    An unseeded model passes discovery-free tests and 404s only at run time (the
    exact bug class the paid lane hunts), so the lane's own roster must be seed-
    backed before anyone presses the paid button. A textual pin on the seed file is
    deliberate: the SDK venv cannot import aigateway (separate uv projects), and the
    seed list is an append-mostly literal, so exact-string presence is stable.
    """
    seeds_source: str = _SEEDS_FILE.read_text(encoding="utf-8")
    missing: list[str] = [
        model for model in (*MEMBER_MODELS, SYNTHESIZER_MODEL) if f'"{model}"' not in seeds_source
    ]
    assert not missing, (
        f"paid-lane panel models missing from the gateway seed list ({_SEEDS_FILE}): "
        f"{missing} — re-pin the panel to seeded models or seed these first "
        f"(a live run would otherwise 404 at dispatch)"
    )
