import screamingface as sf

recipe = sf.Fanout(
    ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]
) >> sf.Synthesize("openrouter/google/gemini-3.1-pro-preview")

candidate_url4 = sf.InferenceClient(recipe).endpoint().model
print(candidate_url4)
