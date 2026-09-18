"""The model world this screamingface-engine deployment declares.

WHY a composition module: the registry machinery does not know which providers exist, exactly as
``benchmarks/builtins.py`` keeps protocol-neutral registry code from importing concrete protocols.
This is the ONE place a deployment chooses its declared model world.

INVARIANT: this world is EXHAUSTIVE over aigateway's COMPILED seeds — every id its plugins declare
appears here, and ``test_declared_models_match_aigateway.py`` asserts set equality in both
directions. Exhaustive does NOT mean "everything a deployment serves":
``AIGW_OPENROUTER_DEFAULT_MODELS`` and ``AIGW_HUGGINGFACE_DEFAULT_MODELS`` replace their lists at
deploy time, and ollama discovers its models at run time with no compiled list. Those deployments
add entries through ``url4.json``, which stays additive for exactly that reason.

AIDEV-NOTE: a declared route is NOT an enabled deployment. OpenRouter sits behind
``AIGW_OPENROUTER_ENABLED``; a route whose provider is disabled or uncredentialed resolves here and
then fails at the gateway, inside the user's expression. That is the accepted cost of declaring the
full compiled set (OME-859 spec §6 consequence 1) — before it, the same call failed earlier and
more clearly, as an unknown route.
"""

from screamingface_engine.models.registry import ModelRegistry
from screamingface_engine.models.seeds.anthropic import ANTHROPIC
from screamingface_engine.models.seeds.antigravity import ANTIGRAVITY
from screamingface_engine.models.seeds.codex import CODEX
from screamingface_engine.models.seeds.gemini_cli import GEMINI_CLI
from screamingface_engine.models.seeds.huggingface import HUGGINGFACE
from screamingface_engine.models.seeds.openrouter import OPENROUTER

BUILTIN_MODEL_WORLD = ModelRegistry(
    (ANTHROPIC, ANTIGRAVITY, CODEX, GEMINI_CLI, HUGGINGFACE, OPENROUTER)
)

__all__ = ["BUILTIN_MODEL_WORLD"]
