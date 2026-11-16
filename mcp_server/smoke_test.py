"""Smoke-Test: verbindet sich als echter MCP-Client gegen den laufenden Server.

Aufruf im Container:
    docker compose exec mem0-mcp python smoke_test.py --token mcp_...

Ohne --token (nur mit MCP_AUTH_DISABLED=true) wird kein Authorization-Header gesendet.
"""

import argparse
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _fmt(result) -> str:
    parts = []
    for content in getattr(result, "content", None) or []:
        text = getattr(content, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) or str(result)


async def run(base_url: str, token: str | None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(f"{base_url.rstrip('/')}/mcp", headers=headers) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Verfügbare Tools:", ", ".join(t.name for t in tools.tools))

            print("\n== add_memory ==")
            r = await session.call_tool(
                "add_memory", {"text": "Smoke-Test: Mein Name ist Bojan und ich teste Mem0."}
            )
            print(_fmt(r))

            print("\n== search_memories ==")
            r = await session.call_tool("search_memories", {"query": "Wie ist mein Name?"})
            print(_fmt(r))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("MCP_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("MCP_TOKEN"))
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token))


if __name__ == "__main__":
    main()