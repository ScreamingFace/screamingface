import screamingface as sf

client = sf.Client()

for model in ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]:
    reply = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What is the capital of France?"}],
    )
    print(model, reply.text)
