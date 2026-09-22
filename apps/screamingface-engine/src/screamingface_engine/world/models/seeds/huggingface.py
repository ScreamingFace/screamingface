"""huggingface model seeds — mirrors ``aigateway/plugins/huggingface_provider/settings.py``.

Slugs are copied verbatim from that list, so the two can be compared by eye. The canonical
``huggingface/`` prefix is applied by :meth:`ProviderSeed.ids`, never written here.

AIDEV-NOTE: when aigateway's list changes, ``test_declared_models_match_aigateway.py`` fails
until this tuple matches. Add or remove the slug; never edit the guard.
"""

from screamingface_engine.world.models.registry import ProviderSeed

HUGGINGFACE = ProviderSeed(
    provider="huggingface",
    slugs=(
        "huggingface/openai/gpt-oss-120b:cerebras",
        "huggingface/Qwen/Qwen3-Coder-480B-A35B-Instruct:novita",
        "huggingface/deepseek-ai/DeepSeek-R1:novita",
        "huggingface/google/gemma-2-2b-it:featherless-ai",
        "huggingface/meta-llama/Llama-3.1-8B-Instruct:nscale",
        "huggingface/moonshotai/Kimi-K3:deepinfra",
        "huggingface/Qwen/Qwen3.8-2.4T-A95B:together",
        "huggingface/zai-org/GLM-5.2:deepinfra",
        "huggingface/deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra",
        "huggingface/tencent/Hy3:deepinfra",
        "huggingface/thinkingmachines/Inkling:together",
        "huggingface/nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:deepinfra",
        "huggingface/MiniMaxAI/MiniMax-M3:deepinfra",
        "huggingface/meta-models/Muse-Glimmer-30B:together",
        "huggingface/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16:fireworks-ai",
        "huggingface/openai/gpt-oss-20b:deepinfra",
        "huggingface/meta-llama/Llama-4-Scout-17B-16E-Instruct:nscale",
        "huggingface/google/gemma-4-31B-it:deepinfra",
        "huggingface/XiaomiMiMo/MiMo-V2.5:deepinfra",
        "huggingface/microsoft/phi-4:deepinfra",
        "huggingface/thinkingmachines/Inkling-Small:together",
        "huggingface/google/gemma-3-4b-it:deepinfra",
        "huggingface/CohereLabs/c4ai-command-a-03-2025:cohere",
        "huggingface/deepseek-ai/DeepSeek-R1-Distill-Llama-8B:nscale",
    ),
)

__all__ = ["HUGGINGFACE"]
