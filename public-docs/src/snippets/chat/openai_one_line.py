import json

import screamingface as sf

# Before: client = openai.OpenAI(api_key="sk-...")
client = sf.Client(api_key="sk-...")  # the key is accepted, not kept and not sent

MODEL = "openrouter/openai/gpt-5.5"
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather of a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]
messages = [{"role": "user", "content": "What is the weather in Paris?"}]

reply = client.chat.completions.create(
    model=MODEL, messages=messages, tools=tools, temperature=0.2
)
message = reply.choices[0].message
messages.append(message)
for call in message.tool_calls or []:
    city = json.loads(call.function.arguments)["city"]
    messages.append(
        {"role": "tool", "tool_call_id": call.id, "content": f"Sunny in {city}"}
    )

final = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
print(final.choices[0].message.content)
print(final.usage.total_tokens)
