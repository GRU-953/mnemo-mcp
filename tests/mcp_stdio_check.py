"""End-to-end check of the Mnemo MCP server over the real stdio transport:
initialize -> list tools -> call a few read-only tools. Run from repo root:

    ./.venv/bin/python tests/mcp_stdio_check.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main() -> int:
    params = StdioServerParameters(
        command=os.path.join(ROOT, ".venv", "bin", "python"),
        args=["-m", "mnemo.server"],
        env={**os.environ, "PYTHONPATH": ROOT, "PYTHONUNBUFFERED": "1"},
        cwd=ROOT,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            print(f"initialize OK — {len(tools)} tools: {[t.name for t in tools]}")

            r = await session.call_tool("memory_status", {})
            txt = r.content[0].text
            print(f"\nmemory_status -> {len(txt)} chars; ollama up = {'\"up\": true' in txt}")

            r = await session.call_tool("memory_list_projects", {})
            print(f"memory_list_projects -> {r.content[0].text[:200]}")

            r = await session.call_tool("memory_overview", {"project": "mini-lex"})
            print(f"\nmemory_overview(mini-lex) -> {len(r.content[0].text)} chars "
                  f"(starts: {r.content[0].text[:60]!r})")

            r = await session.call_tool("memory_expand", {"entity": "ADEX Group", "project": "mini-lex"})
            print(f"\nmemory_expand(ADEX Group) ->\n{r.content[0].text[:400]}")

    print("\nMCP STDIO CHECK: OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
