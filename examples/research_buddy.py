"""Research Buddy — sample agent that calls LLMs through the unsinkable shim."""

from __future__ import annotations

import json
import os
import sys

from unsinkable import OpenAI
from unsinkable.config import get_settings


def web_search(query: str) -> str:
    return json.dumps(
        {
            "query": query,
            "results": [
                {"title": f"Top result for '{query}'", "snippet": "Placeholder snippet."},
                {"title": "Wikipedia overview", "snippet": "Encyclopedia entry."},
            ],
        }
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns top results as JSON.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def ask(client: OpenAI, model: str, question: str) -> str:
    messages = [
        {"role": "system", "content": "You are Research Buddy. Use web_search when helpful."},
        {"role": "user", "content": question},
    ]
    for _ in range(4):
        resp = client.chat.completions.create(model=model, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        messages.append(msg.model_dump())
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = web_search(**args) if call.function.name == "web_search" else "unknown tool"
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
    return "(gave up after 4 tool hops)"


def main() -> None:
    settings = get_settings()
    model = os.environ.get("UNSINKABLE_MODEL", settings.unsinkable_default_model)
    client = OpenAI()

    question = " ".join(sys.argv[1:]) or "What's new in Rust 1.80?"
    print(f"[Research Buddy via {model}] > {question}")
    answer = ask(client, model, question)
    print(answer)


if __name__ == "__main__":
    main()
