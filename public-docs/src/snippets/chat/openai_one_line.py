import screamingface as sf

# Before: client = openai.OpenAI(api_key="sk-...")
client = sf.Client(api_key="sk-...")  # the key is accepted, not kept and not sent

MODEL = "openrouter/openai/gpt-5.5"
messages = [{"role": "user", "content": "What is the capital of France?"}]

reply = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.2)
print(reply.choices[0].message.content)

messages.append(reply.choices[0].message)
messages.append({"role": "user", "content": "And of Italy?"})

final = client.chat.completions.create(model=MODEL, messages=messages)
print(final.choices[0].message.content)
print(final.usage.total_tokens)
