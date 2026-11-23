import screamingface as sf

llm = sf.InferenceClient()

for model in ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]:
    reply = llm.chat.completions.create("What is the capital of France?", model=model)
    print(model, reply.text)
