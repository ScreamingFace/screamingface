import screamingface as sf

ensemble = sf.Fanout(
    ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]
) >> sf.Synthesize("openrouter/google/gemini-3.1-pro-preview")

llm = sf.InferenceClient(ensemble)
reply = llm.chat.completions.create("What is the capital of France?")

print(reply.text)
print(reply.choices[0].message.content)
print(reply.usage.total_tokens)
print(reply.cost_usd, reply.screamingface.status)
