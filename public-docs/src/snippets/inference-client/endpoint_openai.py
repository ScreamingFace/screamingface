from openai import OpenAI

import screamingface as sf

ensemble = sf.Fanout(
    ["openrouter/deepseek/deepseek-v4-flash", "openrouter/openai/gpt-5.5"]
) >> sf.Synthesize("openrouter/google/gemini-3.1-pro-preview")

endpoint = sf.InferenceClient(ensemble).endpoint()
client = OpenAI(
    base_url=endpoint.base_url,
    api_key="not-used",
    default_headers=dict(endpoint.headers),
)

completion = client.chat.completions.create(
    model=endpoint.model,
    messages=[{"role": "user", "content": "What is the capital of France?"}],
)
print(completion.choices[0].message.content)
