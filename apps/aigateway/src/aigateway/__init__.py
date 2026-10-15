"""LiteLLM-compatible AI gateway for ScreamingFace."""

import os

# WHY: litellm decides which parameters each model accepts (``reasoning_effort`` among them)
# from its model map, which it loads once, at import. Left alone, it downloads that map from
# litellm's GitHub main branch on every start, so the gateway's behaviour can change on a
# restart with no deploy and no lockfile change: on 2026-10-15 the downloaded map had lost
# all 269 OpenRouter entries, and every OpenRouter call that sent a reasoning setting failed
# inside litellm as a provider error. Forcing the map bundled with the pinned litellm version
# ties it to ``uv.lock``, so it changes only when a reviewed PR upgrades litellm.
# INVARIANT: set here, in the package's first module, before anything imports litellm; and set,
# not defaulted, so an inherited ``False`` cannot reopen the download.
# ``tests/unit/test_litellm_model_map_pinned.py`` pins it.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

__version__ = "0.2.0"
