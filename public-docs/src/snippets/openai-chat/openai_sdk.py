import os

from openai import OpenAI

base_url = os.environ.get("ENGINE_BASE_URL", "http://127.0.0.1:9108/v1")
access_token = os.environ.get("CF_ACCESS_TOKEN")
headers = {"Cf-Access-Token": access_token} if access_token else {}

client = OpenAI(
    base_url=base_url, api_key="not-used", default_headers=headers, max_retries=0
)

completion = client.chat.completions.create(
    model="openrouter/deepseek/deepseek-v4-flash",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
)

print(completion.choices[0].message.content)
if completion.usage is not None:
    print(completion.usage.total_tokens)
info = (completion.model_extra or {})["screamingface"]
print(info["status"], info["cost_usd"])
print(info["final_step"])
