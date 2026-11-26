import screamingface as sf

model = sf.Model("openrouter/deepseek/deepseek-v4-flash")

with model.chat.completions.create(
    "Write one sentence about Paris.",
    stream=True,
    stream_options={"include_usage": True},
) as stream:
    for chunk in stream:
        if chunk.choices:
            print(chunk.choices[0].delta.content or "", end="")
        elif chunk.usage is not None:
            print()
            print(chunk.usage.total_tokens)
