"""Read-only owner-key verification; prompts hide keys and no credentials are persisted.

Run from apps/aigateway: .venv/bin/python scripts/verify_openrouter_credits.py
"""

import asyncio
import warnings
from getpass import GetPassWarning, getpass

from aigateway.plugins.openrouter_provider.credits import OpenRouterCredits


def main() -> None:
    # INVARIANT: getpass must never fall back to an input mode that echoes the key.
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            inference = getpass("OpenRouter inference key (hidden): ").strip()
            management = getpass("OpenRouter management key (hidden; optional): ").strip()
        except GetPassWarning:
            raise SystemExit(
                "Run this check in an interactive terminal with hidden input"
            ) from None
    if not inference:
        raise SystemExit("An inference key is required")
    observation = asyncio.run(OpenRouterCredits().read(inference, management or None))
    print(observation.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
