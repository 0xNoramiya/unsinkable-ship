"""Research Buddy — sample agent. Uses unsinkable.OpenAI for resilient LLM
calls and unsinkable.mcp.ResilientMcpClient for resilient tool calls."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from unsinkable import AsyncOpenAI
from unsinkable.config import get_settings
from unsinkable.mcp import McpBackend, ResilientMcpClient

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

BACKENDS = [
    McpBackend("primary", PY, [str(REPO_ROOT / "examples/mcp_servers/search_primary.py")]),
    McpBackend("secondary", PY, [str(REPO_ROOT / "examples/mcp_servers/search_secondary.py")]),
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns top results as text.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


async def ask(client: AsyncOpenAI, mcp: ResilientMcpClient, model: str, question: str) -> str:
    messages = [
        {"role": "system", "content": "You are Research Buddy. Use web_search when helpful."},
        {"role": "user", "content": question},
    ]
    for _ in range(4):
        resp = await client.chat.completions.create(model=model, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        messages.append(msg.model_dump())
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            if call.function.name == "web_search":
                try:
                    result = await mcp.call_tool("web_search", args)
                except Exception as e:  # noqa: BLE001
                    result = f"tool error: {e}"
            else:
                result = "unknown tool"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return "(gave up after 4 tool hops)"


async def amain() -> None:
    settings = get_settings()
    model = os.environ.get("UNSINKABLE_MODEL", settings.unsinkable_default_model)
    question = " ".join(sys.argv[1:]) or "What's new in Rust 1.80?"
    print(f"[Research Buddy via {model}] > {question}")
    client = AsyncOpenAI()
    async with ResilientMcpClient(BACKENDS) as mcp:
        answer = await ask(client, mcp, model, question)
    print(answer)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
