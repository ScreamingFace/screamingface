import json

import screamingface as sf

llm = sf.InferenceClient("openrouter/openai/gpt-5.5")

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

reply = llm.chat.completions.create(messages=messages, tools=tools)

for call in reply.tool_calls or ():
    print(call.function.name, json.loads(call.function.arguments))
